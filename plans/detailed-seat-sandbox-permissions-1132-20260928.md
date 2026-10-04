---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 3c61b270
related_issues: [agent-harness#1132, agent-harness#848, agent-harness#895, agent-harness#1104, agent-harness#983, agent-harness#1109, agent-harness#1102, agent-harness#1096, agent-harness#1098, agent-harness#1076, agent-harness#1050, agent-harness#1071, agent-harness#1130, agent-harness#1134, agent-harness#361]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src python -m pytest -q phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_sandbox_permissions.py phase-loop-runtime/tests/test_seat_notices.py phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_harden_evidence_producer.py phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: full-permission review seats inside the per-seat sandbox (agent-harness#1132)

Status: merged plan (agent-harness#1133), amended by the implementation PR with the
president follow-ups F030, F038, F035, F022 and F020. Maintainer decisions D1–D8 were
recorded 2026-09-28.
Spec: agent-harness#1132 and its maintainer decision of 2026-09-28. A seat launched inside the
per-seat sandbox gets full tool permissions regardless of local tool settings, because the
sandbox is the boundary. Outside a sandbox nothing changes. Decisions D1–D8 were ruled by the maintainer
on 2026-09-28 (recorded on agent-harness#1132) and are listed below. Where this plan and the
issue disagree, the issue and those decisions govern.

## Relation to agent-harness#848 (SBXEXEC)

agent-harness#848 and `docs/proposals/review-seat-sandbox.phases.md` describe the full design.
Inference stays in a credentialed, tool-less parent, and reviewed code runs only in a
credential-less, network-less executor over content-addressed layers (SBXEXEC, SBXFETCH,
SBXSEAT). That design is still proposal-only: it is not in `specs/phase-plans-v10.md`.

This plan is a narrower step. It puts the provider CLI itself, holding its own subscription
credential, inside a per-seat filesystem jail and the existing egress namespace. The agent-harness#848
panel called that shape "option (a)" and rejected it for EC-HARDEN-5 (see D3). This plan does
not make SBXEXEC obsolete. It is the step that stops the inlined-patch failure class now
(agent-harness#983, the 512 KiB cap), and it leaves SBXEXEC as the design that could satisfy
EC-HARDEN-5.

## Inputs observed at `input_base_commit`

These are inputs, not outputs.

- **Brokered route choice.** `panel_invoker._default_spawn` sends every authorized review leg
  through `ParentUnixBroker`. The staged tree is built by `review_stage.stage_review_tree`: a
  shallow `file://` clone at the source HEAD, overlaid with the working tree, and marked by
  `.git/phase-loop-source-commit`. It is built only when the authorization carries
  `staged_tree_sha256`.
- **Sandbox capability per leg.** `_SANDBOX_INCAPABLE_BROKERED_LEGS = {claude, gemini}` and
  `sandbox_usable_by` decide which preamble a leg gets. Claude and Gemini always get the
  sealed preamble plus the inlined bundle.
- **Claude.** `_broker_claude_tui_command` passes `--safe-mode`,
  `--setting-sources ""`, `--tools "" --allowedTools ""`, and
  `--disallowedTools Bash,Read,Edit,Write,WebFetch,WebSearch,Task,NotebookEdit`.
  - `_exec_claude_tui_leg` runs it with `tui_cwd = out_dir`, and the environment comes from
    `_broker_subscription_env`. That function is an allowlist: HOME, LANG, LC_*, NO_COLOR,
    PATH and TERM.
  - The transcript path comes from `_claude_project_dir_for_cwd`, which uses `~/.claude/projects`.
  - `_claude_subscription_auth_ok` requires `authMethod == "claude.ai"` and a
    `subscriptionType`.
  - `president_adapter.py` also calls `_broker_claude_tui_command`.
- **Workspace trust.** Claude's workspace-trust modal is answered by the PTY detector
  (`_CLAUDE_TUI_TRUST_*`, typed `claude_tui_workspace_trust_blocked`). agent-harness#1104's
  maintainer decision forbids writing trust into the user's own settings.
- **Codex and grok.** They get the tree through `_brokered_codex_command` and
  `_brokered_grok_command`. Their controls are reported by `_broker_tool_controls`, which
  raises for any other leg.
- **Gemini.**
  - `_brokered_gemini_command` has two branches. The `heartbeat_only` branch (the one boards
    use) has no `--add-dir`. The `bounded` branch adds `--add-dir <tree>`.
  - Settings come from `_broker_agy_settings_bytes`: `_BROKER_AGY_DENY_ACTIONS` plus
    `toolPermission: request-review`.
  - The heartbeat stream refuses "tool or subagent activity observed".
  - The heartbeat owner is `_ReviewMonitor.owned_command`, which runs
    `bwrap --bind / / --dev /dev --proc /proc` plus `gemini_heartbeat.owned_profile` mounts
    (`PROFILE_ID = agy_memfd_home_deny_all_v1`).
  - `tool_denied: headless tool permission auto-denied` is a closed failure template.
  - The agent-harness#525 comment in `_exec_leg` records a live-agy measurement: under `--dangerously-skip-permissions`,
    a file was written outside `--add-dir`, and neither `--sandbox` nor `--mode plan`
    contained it.
- **Isolation today.** `sandbox_egress.isolated_network` gives a filtered network namespace.
  - Its own enforcement report says `filesystem_confined: False`.
  - `_compose_launch_prefix` adds the agent-harness#1109 identity switch and lock-down
    (`unshare --user`, `setpriv --bounding-set=-all`), or an owner `bwrap` with
    `--unshare-user --cap-drop ALL`.
  - `_require_seat_identity` probes the result before every launch.
  - agent-harness#895 (filesystem confinement) is open.
  - **So no shell-capable seat is filesystem-confined today.** Codex's own workspace-write
    sandbox confines its writes, not its reads.
- **Leg detail.** `_HARNESS_DETAIL_CODES`, `_PARAMETER_FREE_FAILURES` and
  `_finalize_leg_detail` (agent-harness#1096, landed by agent-harness#1102) are the closed
  vocabulary. `detail` is failure-shaped.
- **Board summary.** The board summary is the `phase-loop advisor-board` payload in `cli.py`
  (`shortfall`, `legs[].detail`).
- **Evidence verifier.** `scripts/verify_harden_evidence.py` requires
  `provider_input_inline is True` and `provider_live_tree_cwd is False` on every broker record.
- **agy route-core.** `agy_qualification.ROUTE_CORE` (agent-harness#1130) is
  `("gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py")`, and
  `scripts/verify_qualified_agy_image.py --route-core` checks every qualification record
  against it.
- **Governing criteria.** EC-HARDEN-5 is at `specs/phase-plans-v10.md`. EC-EXECFIND-2 and
  EC-EXECFIND-4 are in the same file, under Phase 15.

### CLI flags verified on claw (2026-09-28)

Claude Code 2.1.283 (`claude --help`):
- `--permission-mode <mode>`, whose choices include `bypassPermissions`;
- `--dangerously-skip-permissions`;
- `--tools <tools...>`, where `""` means none and `"default"` means all built-ins;
- `--allowedTools`, `--disallowedTools`, `--add-dir`, `--setting-sources`, `--settings`,
  `--strict-mcp-config`, `--mcp-config`, `--agents`, `--safe-mode`, `--session-id`,
  `--disable-slash-commands`.

Two flags are **excluded**:
- `--bare` never reads OAuth.
- `--restricted` refuses `bypassPermissions`.

The configuration directory is set by `CLAUDE_CONFIG_DIR`. It is an environment variable and
does not appear in `--help`, but it was measured:
- `CLAUDE_CONFIG_DIR=<empty dir> claude auth status --json` gives `loggedIn: false`,
  `configDirectory: <dir>` and `projectsDirectory: <dir>/projects`, and creates
  `<dir>/.claude.json`.
- Adding `CLAUDE_CODE_OAUTH_TOKEN=<dummy>` gives `loggedIn: true, authMethod: "oauth_token"`,
  with no `subscriptionType`. So `auth status` does **not** check that a token is valid.
- `claude setup-token` exists ("Set up a long-lived authentication token (requires Claude
  subscription)").
- The CLI is a single ELF file, `…/@anthropic-ai/claude-code/bin/claude.exe`, under the user's
  npm prefix in `$HOME`.

agy 1.2.12 (`agy --help`):
- `--dangerously-skip-permissions` ("Auto-approve all tool permission requests without
  prompting");
- `--add-dir` (repeatable);
- `--mode accept-edits|plan`;
- `--sandbox` ("terminal restrictions");
- `--input-format`/`--output-format stream-json`, `--print`, `--print-timeout`,
  `--disable-slash-commands`.

The settings-file values of `toolPermission` are **not** in `--help` and are unverified.

Host: bubblewrap 0.6.1, operator uid 1000.

### Additional facts measured on claw (round 1 and round 2)

- `claude --help` describes `--disable-slash-commands` as "Disable all skills".
- The Claude binary contains the string `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, beside
  `CLAUDE_CODE_OAUTH_TOKEN` and `CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR`. That the string is
  present is not proof the behaviour exists; P2 verifies it.
- `/proc/sys/dev/tty/legacy_tiocsti` is `0`.
- `/proc/sys/kernel/yama/ptrace_scope` is `1`.
- `keyctl` (keyutils) is not installed.
- The kernel config has `CONFIG_IA32_EMULATION=y` and `# CONFIG_X86_X32_ABI is not set`.
- agent-harness#1109 maps each seat onto the **operator's own** uid; it provides no separate
  seat account. On claw, `newuidmap` and `newgidmap` are absent (the uidmap package is not
  installed), the operator has no `/etc/subuid` or `/etc/subgid` entry, bwrap is not setuid,
  and util-linux is 2.37.2, whose `unshare` has no `--map-users`. The seat-uid route of D8
  therefore needs a one-time root setup on each host (see "Seat uid").
- The Claude TUI leg is spawned with `start_new_session=True` on a `pty.openpty()` pair
  (`_run_claude_tui_session`).
- agy 1.2.12 has no auth, login or token subcommand.
- The operator's `antigravity-oauth-token` holds `token.access_token`, `token.refresh_token`,
  `token.expiry`, `id_token` and `auth_method`. Only its shape was measured.
- The egress namespace is acquired per leg in `_default_spawn`.
- `review_stage._overlay_working_tree` stages tracked files and untracked files that are not
  ignored. Ignored files are never staged. An untracked secret that is not ignored is part of
  the reviewed content, and the review shows it to every seat today.

### Live probes P1–P5: gate, evidence and stop rules

The probes run in lane L0. Each one builds its own throwaway jail from the **production argv,
environment, mount set, fd kind and seccomp filter** named in this plan; none depends on `seat_jail.py`. Each
probe writes a JSON evidence record under `plans/evidence/`. An amendment commit pins each
record's sha256 before the lanes that need it: P5, P1 and P2 before L1, and P4 then P3 before
L3.
L5 replays, on the final candidate, only the probes that were reached, and each must
reproduce its pinned facts. A recorded stop must reproduce as the same stop. P3 is replayed
only if P4 passed.

A stop in P1 or P2 halts L1–L2 and goes back to the maintainer. A stop in P4 or P3 keeps the
Gemini seat sealed, with the notice named in the stop, and L3 is dropped from scope. Claude
work continues.

- **P5 Seat uid (D8).** P5 runs first. It needs the maintainer's root prerequisite on claw, and
  it never performs that setup itself.
  - Build the D8 prefix with the production pieces: the unmapped holder plus `newuidmap` and
    `newgidmap`, the hand-off chown, bwrap 0.6.1 as H-root without `--unshare-user`, the J14
    filter, and the `setpriv` drop.
  - Record:
    - that bwrap 0.6.1 builds the J1 mount set as H-root;
    - that the pre-drop set bwrap leaves is exactly `CAP_SETUID`, `CAP_SETGID` and
      `CAP_SETPCAP`;
    - the probe's view after the drop: seat ids, `CapPrm/CapEff/CapInh/CapAmb/CapBnd` all 0,
      `NoNewPrivs` 1 and `Seccomp` 2;
    - that `claude --version`, `agy --version`, `node`, `python3` (threads and subprocess),
      `git` and `uv`/`pip` run as the seat uid inside the jail;
    - that the in-H reader can read a 0600 file the seat created.
  - **Stop** if bwrap cannot build the jail as H-root, if any capability survives the drop, or
    if the CLIs do not run. The seat-uid route then does not ship, and the plan returns to the
    maintainer.
  - P1–P4 run on the D8 prefix after P5 passes.
- **P1 Claude private config and PTY.**
  - Run the TUI with the exact production argv (`--safe-mode`, `--setting-sources ""`,
    `--tools default`, `--permission-mode bypassPermissions`) and an empty private
    `CLAUDE_CONFIG_DIR`.
  - The cwd is `/seat/tree`, on a parent-owned PTY in a new session.
  - Record:
    - the `.claude.json` keys that suppress the trust modal and any bypass acknowledgement;
    - whether the TUI renders and accepts input;
    - whether bypass mode is refused for uid 0;
    - whether `node`, `python3` (threads and `subprocess`), `git` and `uv`/`pip` run under the
      exact J14 filter.
  - **Stop** if bypass mode is refused, if a modal cannot be pre-seeded, or if the TUI or any
    of those tools fails under the filter.
- **P2 Claude seat token.**
  - Deliver a real `claude setup-token` token only through a drained pipe named by
    `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, and confirm the interactive TUI authenticates
    and bills to the subscription.
  - Record:
    - the token's scope and expiry;
    - the TUI's signature for a rejected token;
    - whether revocation stops a subsequent launch.
  - The revocation check uses a **sacrificial token**, minted with `claude setup-token` for
    that check alone and revoked by it. The seat token is never revoked by any probe. P2 ends
    by confirming the seat token still authenticates, and L5 uses an unrevoked or freshly
    minted seat token.
  - **Stop** if the fd route does not work, if usage does not bill to the subscription, or if
    revoking the sacrificial token has no effect.
- **P4 agy with the D7 credential.** P4 runs first on the Gemini side.
  - **Delivery.** Build the D7 copy, which is the operator file with `refresh_token` removed and
    `id_token` removed unless agy needs it. Deliver it by the exact production mechanism:
    - a parent-owned 0700 host directory holding only `settings.json` and the copy;
    - that directory bound read-only **as a directory** at agy's config directory;
    - every ancestor of that directory on the read-only root.
  - **Record, measured parent-side:**
    - the path agy opens for its credential, and every path agy writes;
    - whether agy completes a turn;
    - the token's real lifetime, from its first use to the provider's first rejection;
    - the token's OAuth scopes and audience, from Google's tokeninfo endpoint called by the
      parent (the token itself is never recorded);
    - agy's stream-json signature at expiry;
    - whether agy picks up a copy the parent **renames into the bound directory**
      mid-session;
    - whether the parent can refresh the operator credential **outside the jail**. That
      refresh uses a pinned, tool-less, workspace-less, inference-free invocation: argv
      recorded, cwd an empty 0700 temporary directory, stdin `/dev/null`, a bounded wall clock.
  - **Stop, and keep Gemini sealed**, in any of these cases:
    - agy does not run with the copy (`gemini_seat_credential_unusable`);
    - agy obtains a working token inside the jail after the copy expires, which would mean the
      copy is not its only credential (`gemini_seat_credential_unusable`);
    - agy needs to write inside its config directory (`gemini_seat_credential_unusable`);
    - the scopes go beyond inference (`gemini_seat_token_scope_excess`). P4 also reports the
      measured scopes to the maintainer. Gemini stays sealed with this code until the
      maintainer rules and P4 is re-run.
- **P3 agy tools and workspace configuration.** P3 runs after P4, using the P4 credential.
  - Record:
    - the `toolPermission` value, or whether `--dangerously-skip-permissions` alone is enough;
    - the complete set of stream-json event types, with the event that starts each tool call
      and each subagent call;
    - **every file agy loads from its cwd or from `--add-dir`**: settings, rules, context,
      MCP, hooks and agents, and what disables each one.
  - **Stop, and keep Gemini sealed with `gemini_seat_stream_split_unavailable`**, in either
    case:
    - subagent and tool events cannot be told apart reliably by type;
    - any workspace file that agy loads cannot be disabled.

### Probe records (pinned 2026-09-29, claw; host prerequisite in place)

| probe | record (`plans/evidence/seat-jail-1132/`) | sha256 | result |
|---|---|---|---|
| P5 | `p5-seat-uid.json` | `36c9d77d198bfd41d10a0e75bf82a3f660e1e0dd7f76944dfe029f29c84ee8b7` | pass |
| P1 | `p1-claude-config-pty.json` | `bec8bd08b9ccb99c7d3e774396a27b37b04a615347e77fb43356d2fbf7cf7ad3` | pass |
| P2 (2026-10-03) | `p2-claude-seat-token.json` | `8dead61a7c935d411ca7a6408f6b583523dabeee35fdb1999115518b4a9b4d3d` | **pass**: fd route authenticates and the seat quotes a tool's output; a rejected token is `auth_failure`. Not measured: scope/expiry, billing, revocation (sacrificial token) |
| P4 | `p4-agy-d7-credential.json` | `121ef9386e1412d30d4d5b202a7b73b59e07dbd8679b1c4ac2425f25ab97b035` | **stop**: `gemini_seat_token_scope_excess` |
| P4 containment (maintainer ruling "prove then enable") | `p4-containment.json` | `fe71bb819a2e701e5e60685e79aa33602e9ab56c8d19b42d70a49b0d6b6cab45` | **stop**: `gemini_seat_egress_unconfined`; (a) holds, (b) fails |
| P3 | — | — | not run: P3 runs only after P4 passes |
| EC-EXECFIND-2 jail falsifiers (claw) | `execfind2-jail-qualification-claw.json` (public summary; full evidence in the per-host store) | see file | **pass**, against the EXECFIND falsifier-run layout (agent-harness#1163/#1164) |

**Measured deviations from the plan's literal argv (accepted by the lead 2026-09-29; the
board ratifies them).** P5 changed the D8 launch order as measured. None of these is a P5
stop, because each restores a property the plan requires:
- bwrap run as H-root keeps every capability. `--cap-drop ALL` therefore precedes the three
  `--cap-add`s, and the effective set before the drop is exactly SETUID, SETGID and SETPCAP.
- With no DAC capability, H-root cannot `--chdir` into the seat's 0700 tree. The seat enters
  `/seat/tree` after the drop, with `/usr/bin/env --chdir`.
- bwrap creates the parent of a file bind as 0700 root. `/seat`, `/seat/bin`, `/seat/review`
  and `/etc` are therefore created 0755.
- P1 found the tmpfs mounts must be 1777.

**P1 pinned the Claude pre-seed:** `hasCompletedOnboarding`, `bypassPermissionsModeAccepted`
and `projects["/seat/tree"].hasTrustDialogAccepted`. Removing any one of them brings back
exactly one modal. P1 also recorded:
- the bypass-acknowledgement text;
- that bypass mode is refused for uid 0;
- that input is accepted;
- that planted `CLAUDE.md`, hooks and `.mcp.json` did not load.

The P1 token was a dummy on the production fd channel, because P2 is pending.

**Gemini scope ruling ("prove then enable", maintainer, 2026-09-29).** Gemini gets its
tools only if a live probe proves two things:
- **(a)** the jailed copy holds only a short-lived access token;
- **(b)** jail egress reaches only agy's inference hosts.

The containment probe proved (a):
- the staged copy's keys are `auth_method`, `token.access_token`, `token.expiry` and
  `token.token_type`, with no refresh token, client secret or id token;
- about 36 minutes of lifetime remained at staging;
- the turn succeeds, the copy is unchanged afterwards, no token appears in any
  seat-writable directory, and an expired copy fails.

The probe failed (b):
- agy's only inference host is `daily-cloudcode-pa.googleapis.com`;
- `storage`, `cloudresourcemanager`, `compute` and `iam.googleapis.com` all return real
  HTTP replies (400/404) from inside the jail;
- `iam.googleapis.com` resolves to the same front-end addresses as the inference host;
- the egress namespace filters by destination CIDR only.

Gemini therefore stays sealed with `gemini_seat_egress_unconfined`. The scopes are not
recorded as a contained residual. P3 was not run and L3 is not built.

**The original P4 stop.** agy completed a turn on the D7 copy, delivered as a read-only directory with
`installation_id` provided and only `cache/` writable. But the access token's scopes
include `cloud-platform`, `cclog` and `experimentsandconfigs`, which go beyond inference.
Gemini therefore stays sealed with `gemini_seat_token_scope_excess` until the maintainer
rules and P4 is re-run, and L3 is dropped from this PR.

P4 also recorded:
- the expiry signature: `authentication failed or timed out`, after a 60 s wait for
  interactive OAuth;
- that the outside refresh `agy models` works.

It did not measure whether agy picks up a copy renamed in mid-session.

## Invariants (each has a named falsifier in "Tests")

J1–J4 and J10–J13 apply to **jailed** seats: Claude, and Gemini if L3 is in scope. Codex and
grok stay unjailed until the agent-harness#895 follow-up. They carry
`seat_filesystem_unconfined`, and D3 names what they can reach.

- **J1 Filesystem jail.** The in-jail `/proc/self/mountinfo` equals exactly this set:
  - Read-only system paths: `/usr`, `/lib*`, `/bin`, `/sbin`, and this `/etc` subset: `ssl`,
    `resolv.conf`, `hosts`, `nsswitch.conf`, `passwd`, `group`, `localtime`, `ld.so.cache`,
    `ld.so.conf`, `ld.so.conf.d`, `alternatives`.
  - The provider executable, read-only at `/seat/bin/<leg>`. For agy it is the sealed memfd.
  - The bundle and instructions, delivered by sealed memfd `--ro-bind-data` at `/seat/review/`.
    No host path backs them.
  - The staged tree, read-write, at `/seat/tree`.
  - The private HOME, read-write, at `/seat/home`. It is fresh per launch.
  - The output directory, read-write, at `/seat/out`. It is fresh per launch.
  - For Gemini only: the P4 config directory, as a read-only directory bind, plus the writable
    paths P4 recorded, each a read-write bind into `/seat/home`.
  - A tmpfs at `/tmp` and `/dev/shm`, the bwrap `/dev`, and a fresh `/proc`.

  The root is remounted read-only, so no mount point's ancestor can be renamed or shadowed.
  **No credential is a mount for Claude.**
- **J2 Writes confined.** Host-backed writes reach only `/seat/tree`, `/seat/home` and
  `/seat/out`. Everything else writable is a tmpfs. Round-end deletion is an fd-relative walk
  that never follows links.
- **J3 Credential channels.**
  - **Claude.** The seat token enters only as one drained pipe fd.
  - **Gemini.** The only credential is the D7 copy in its read-only config directory.
  - **Environment.** The jail environment is exactly the declared set.
  - **Descriptors.** The jail's open descriptors are exactly the declared set per leg: 0, 1, 2
    and, for Claude, the token fd.
  - **Keyrings and uid-owned kernel objects.** The seat runs as its own subordinate uid (J15,
    D8) with no supplementary groups. Toward the operator's kernel objects it has **exactly
    the access of an unrelated local uid**:
    - **Denied:** anything granted to the operator by owner, group or possessor permission.
      That covers keys read or searched by serial, and AF_ALG keys referenced by serial.
    - **Still allowed:** grants to "other". This is a named D3 residual: operator objects the
      operator has made world-accessible, which any local user can already use.
    - Possession is independent of uid. So the seat also joins a fresh anonymous session
      keyring, and inherits none of the operator's.
    - J14's denial of `keyctl`, `add_key`, `request_key` and `socket(AF_ALG, …)` stays as
      defence in depth. io_uring is **not** denied, because libuv and node may use it. An
      `IORING_OP_SOCKET` AF_ALG socket is therefore limited only by the uid rule, within the
      "other" residual.
  - **Absent.** The operator's primary logins, `~/.ssh`, `~/.codex`, `~/.gemini`, `~/.config`,
    vendor API key variables, and the operator's session and user keys.
  - **Where the token can appear.** A harness-constructed launch argument or environment value
    never contains it. Neither does any evidence, log, leg record, board payload or published
    review text. Processes and files **the seat itself creates** can contain it, and that is the
    D3 residual.
- **J4 No sibling access.** A jailed seat cannot do any of the following to another seat's
  tree, output, HOME, transcript, processes, sockets or keyrings: read them, write them, signal
  them, attach to them, or connect to them. Concurrent seats hold distinct subordinate uids
  (J15), so file permissions (DAC) are a second, independent layer.
- **J5 Network unchanged.** The seat runs in its own egress namespace. There is no
  `--unshare-net` and no `/run` bind.
- **J6 Lock-down (agent-harness#1109 and agent-harness#999 invariants).** The identity
  probe runs through the exact jail prefix and must show all of the following:
  - the seat uid and gid, which are the leased subordinate ids (J15);
  - `CapPrm/CapEff/CapInh/CapAmb = 0`;
  - `CapBnd = 0`, which is the agent-harness#999 invariant for a jailed seat;
  - `NoNewPrivs: 1`;
  - `Seccomp: 2`, with the production filter digest.
- **J7 Fail closed, in a fixed order.** The steps below run in order and the first one that
  fails wins, so every failure yields exactly one code.
  0. **No staged tree.** If the authorization approved no staged tree, the seat takes the
     sealed route with `seat_sandbox_not_staged`. Nothing else is evaluated, because without a
     tree there is nothing to jail.
  1. **Recorded route stop (Gemini).** If L0 recorded a P4 or P3 stop, the seat takes the
     sealed route with that stop's code. The stop codes are `gemini_seat_credential_unusable`,
     `gemini_seat_token_scope_excess` and `gemini_seat_stream_split_unavailable`.
  2. **`seat_sandbox_capable()`.** This includes the TIOCSTI precondition and the seat-uid
     prerequisite (J15): setuid `newuidmap` and `newgidmap`, a subordinate uid and gid range
     for the operator with at least one free seat id, and an operator uid that is not 0. It runs after the
     public-entry authorization and before staging. If it fails, the seat takes the sealed
     route with `seat_sandbox_unavailable_host`, `seat_sandbox_unavailable_tiocsti` or
     `seat_sandbox_unavailable_seat_uid`.
  3. **Credential presence.**
     - No Claude token file: the sealed route with `claude_seat_token_missing`.
     - No operator agy file: the sealed route with `gemini_seat_credential_missing`.
  4. **Qualification (Gemini).** This step runs only when steps 1–3 left the tooled route
     available. The image must cover the tooled profile; if it does not, the seat takes the
     sealed route with `gemini_seat_profile_unqualified`.
  5. **Pre-launch steps.** These are the jail build (seccomp filter included), the namespace,
     identity, the pre-seed, the token read, the Gemini copy build and the pre-exec tree
     re-hash. A failure refuses the leg with its code and **zero provider launches**.
  6. **Runtime checks.** These are output safety, the token scan, stream-split refusals and
     token expiry. There is no post-run re-hash: the tree is the seat's writable workspace, and
     the bundle is a sealed memfd that the seat cannot change. A failure ends or rejects the
     leg with its code, and it **never launches a fallback**.

  The sealed route is reached only through steps 0–4, and always with a notice.
- **J8 Honest evidence.**
  - Records carry `provider_input_mode`, the tool controls, the jail profile id and digest, and
    `sandbox_filesystem_confined`.
  - A sealed launch is byte-identical to `input_base_commit`.
  - `verify_harden_evidence.py` reports EC-HARDEN-5 as UNMET, with residual
    agent-harness#361, on every tooled or pointer record.
- **J9 Outside a sandbox nothing changes.** The sealed Claude and agy launches and the
  president launch are golden-identical to `input_base_commit`.
- **J10 Every parent read of a seat-writable object is hardened.** This covers the output, the
  transcript, the final-message blocks, the pre-seed write, and the **tree re-hash**.
  - Every such operation is fd-relative from a directory fd opened before launch, one path
    component at a time, with `O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`.
  - A file must pass an `fstat` regular-file check and a size cap.
  - The tree re-hash `lstat`s symlinks and hashes their target strings. It never follows them.
  - Any other result refuses the leg with `seat_sandbox_refused:output_unsafe`, or with
    `seat_sandbox_refused:stage_changed` for the tree.
- **J11 No keystroke injection.** The seat is never attached to the operator's terminal:
  - its controlling terminal is none, or, for Claude, only the harness PTY;
  - agy runs with `--new-session`;
  - the host must satisfy `dev.tty.legacy_tiocsti = 0`, and a missing sysctl counts as unsafe.
- **J12 Planted configuration is inert.**
  - Claude: `.claude/` settings, hooks, skills and agents, `.mcp.json` and `CLAUDE.md` in
    `/seat/tree` are never loaded.
  - agy: every workspace file that P3 recorded is never loaded.
- **J14 No nested namespaces and no key syscalls.** The jail installs a seccomp filter through
  bwrap `--seccomp FD`. `seat_jail` builds it as a static classic-BPF program for the **host's
  own architecture only** (x86_64 or aarch64). Its rules are evaluated in this fixed order:
  1. **Architecture.** `seccomp_data.arch` other than the build architecture →
     `SECCOMP_RET_KILL_PROCESS`. This refuses i386 `int 0x80` on x86_64 and AArch32 on aarch64.
  2. **x32 (x86_64 only).** `nr >= 0x40000000` (`__X32_SYSCALL_BIT`) → EPERM, before any
     per-syscall rule. Every x32 call is refused whatever its number: x32 syscalls arrive with
     `arch == AUDIT_ARCH_X86_64`, so a native-number rule would not match them. This is the
     systemd and Docker pattern.
  3. **Per-syscall denials**, on native numbers:
     - `unshare` and `clone`, when their flags include `CLONE_NEWUSER` or `CLONE_NEWNS` → EPERM;
     - `setns` → EPERM **unconditionally**, because `nstype == 0` evades any flag mask;
     - `clone3` → ENOSYS unconditionally. Classic BPF cannot read clone3's flags, and ENOSYS
       makes libc fall back to `clone`;
     - `keyctl`, `add_key` and `request_key` → EPERM;
     - `socket` and `socketpair` when the domain argument (low 32 bits) is `AF_ALG` (38) →
       EPERM;
     - `ioctl`, when the **low 32 bits** of the request equal `TIOCSTI` or `TIOCLINUX` →
       EPERM. The kernel truncates the request to 32 bits, so the high half is ignored.
  4. **Default:** allow.

  bwrap 0.6.1 has no `--disable-userns`, so the filter is the enforcement. Without it, a seat
  could create a nested user and mount namespace and overmount a config ancestor on the
  read-only root.

  **Probe coverage.** P1, P3 and P4 run the real CLIs under this exact filter: claude, agy,
  node, python (including threads and subprocess), git and uv/pip. A CLI that needs a denied
  call is caught before implementation. If agy's own `--sandbox` needs a denied call, it is
  dropped; the jail is the boundary.

  **Filter identity.** J6 checks that the installed filter's digest is the production filter
  digest.
- **J15 The seat runs under a subordinate uid (D8).**
  - Every jailed seat runs as a host uid and gid leased from the operator's subordinate range.
    It never runs as the operator's uid or as uid 0 in any namespace.
  - The seat holds no capability in the namespace that maps the operator, or in any other.
  - It can write only files owned by its own seat uid, and every such file sits under its
    three host-backed directories.
  - DAC is a second layer beneath J1's read-only mounts: no operator-owned file reachable
    through any mount is writable by the seat uid.
- **J13 One code per failure.**
  - Every failure has exactly one closed-vocabulary code, and every code has a delivery test.
  - On the jailed route an identity failure is `seat_sandbox_refused:identity`.
    `seat_identity_unverified` remains only for the unjailed agent-harness#1109 route.

## Design

### Seat jail (new module `seat_jail.py`, beside `sandbox_egress.py`)

`build_seat_jail(leg, review_dir, staged_tree, provider_executable, *, bundle_memfds,
credential)` returns a `SeatJail` with these fields:
- the `process_owner` argv;
- the host-to-jail path map;
- the explicit environment;
- the declared descriptor set;
- the directory fds for `seat-out` and `seat-home`, both created fresh for each launch;
- the profile id and digest.

**Host layout under `review_dir`:**
- `reviewed-tree/` (read-write, bound at `/seat/tree`);
- `seat-home/` (mode 0700, fresh);
- `seat-out/` (mode 0700, fresh);
- for Gemini, `gemini-config/`: parent-built, owned by the operator with group n at modes
  0750/0440 (set by the hand-off), and bound read-only.

The bundle and instructions have no host path in the jail.

**bwrap flags:**
- `--die-with-parent --unshare-pid --unshare-ipc --unshare-uts --unshare-cgroup-try`, with no
  `--unshare-user`, and with exactly `--cap-add CAP_SETUID --cap-add CAP_SETGID --cap-add
  CAP_SETPCAP` (see "Seat uid");
- `--proc /proc --dev /dev --tmpfs /tmp --tmpfs /dev/shm`;
- the J1 binds, then `--remount-ro /`, `--chdir /seat/tree`, `--clearenv` and `--seccomp FD`
  (J14).

The environment is set by `--setenv` pairs with non-secret values: `HOME`,
`CLAUDE_CONFIG_DIR`, the XDG directories, `PATH=/seat/bin:/usr/bin:/bin`, `LANG`, `TERM`,
`DISABLE_AUTOUPDATER=1`, and the name and number of the token fd. agy adds `--new-session`.
The launch passes only the declared fds (`pass_fds`, `close_fds=True`). The jail never uses
`--bind / /` or `--unshare-net`.

### Seat uid (D8)

**Host prerequisite.** The maintainer runs this once per host, as root. It is never run by the
runtime or by this plan's lanes.
- `apt install uidmap`, which provides setuid `newuidmap` and `newgidmap`.
- `usermod --add-subuids <start>-<end> --add-subgids <start>-<end> <operator>`. The range
  needs at least 1 + the maximum number of concurrent jailed seats; 65536 is conventional.

If the prerequisite is missing, J7 step 2 sends the seat to the sealed route with
`seat_sandbox_unavailable_seat_uid`. L5 and the live board both require it, and it is listed in
"Lanes".

**The mapping.**
- The egress holder's user namespace H is created **without** a map (`unshare --user --net
  --mount`), and the child waits on a pipe.
- The parent then runs `newuidmap <pid> 0 <operator uid> 1 1 <subuid start> <count>`, and
  `newgidmap` with the same shape. util-linux 2.37.2 has no `--map-users`, so this is done
  directly, the way rootless container runtimes do it.
- In H, uid 0 is the operator and uids 1..count are the subordinate range.
- Only the seat-uid route uses this holder. The sealed route, and the Codex and grok routes,
  keep today's holder byte-for-byte.
- Each launch leases one seat id n in 1..count with an `flock` on
  `$XDG_RUNTIME_DIR/phase-loop/seat-uid/<n>.lock`, held for the life of the leg. Concurrent
  seats never share a uid.

**Launch order inside H.** Each process below is exec'd by the one before it:
1. `seat_keyring_exec` joins a fresh anonymous session keyring. It runs before the filter,
   because J14 denies `keyctl`.
2. `nsenter` enters H. The process is H-root, which is the operator's uid on the host, with
   full capabilities in H only.
3. A hand-off step still runs as H-root.
   - It first proves that the staged tree consists of **private inodes**. `stage_review_tree`
     copies the tree and never hard-links it, and an fd-relative, no-follow walk checks
     `st_nlink == 1` for every non-directory entry. Any other link count refuses the leg with
     `seat_sandbox_refused:stage_not_private` **before any chown**. Without this check, H-root's
     `CAP_FOWNER` would re-own an operator inode that also has a name outside the stage.
   - It then runs the chown as an fd-relative walk that never follows links (`fchownat` with
     `AT_SYMLINK_NOFOLLOW`), setting `n:n` over `reviewed-tree/`, `seat-home/` and
     `seat-out/`. For Gemini it leaves `gemini-config/` owned by H-root (the operator), with
   group n and modes 0750 on the directory and 0440 on its files. The seat reads the config
   through the group grant, and it can neither write nor `chmod` a directory it does not own. It also opens the directory fds
   the parent keeps for J10.
4. `bwrap` runs as H-root **without** `--unshare-user`. It needs no new user namespace,
   because H-root holds `CAP_SYS_ADMIN` in H. It creates the mount, pid, ipc, uts and cgroup
   namespaces with the J1 mounts, then installs the J14 filter with `--seccomp`. The
   `--ro-bind-data` memfds use `--perms 0444`, and the provider image uses 0555, so seat uid
   n can read them.

   bwrap leaves the sandboxed process **no** capabilities by default (bwrap(1): "By default
   no caps are left in the sandboxed process"). It is therefore given exactly three with
   `--cap-add`, each needed for the next step's drop and nothing else:
   - `CAP_SETUID`, for `--reuid n`;
   - `CAP_SETGID`, for `--regid n` and `--clear-groups`;
   - `CAP_SETPCAP`, for `--bounding-set=-all`, because `PR_CAPBSET_DROP` needs it.

   Nothing else is added.
5. `setpriv --reuid n --regid n --clear-groups --inh-caps=-all --ambient-caps=-all
   --bounding-set=-all --no-new-privs --` performs the drop:
   - `setresuid` from 0 to n clears the permitted and effective sets, including the three added
     capabilities, because no keep-caps is set;
   - the bounding set and the inheritable and ambient sets are emptied;
   - no-new-privs is set.

   The seat therefore holds `CapBnd = 0` and no capability in H (J6, agent-harness#999).
6. The provider runs as n.

The J14 filter is inherited by `setpriv` and the provider. It does not block `setresuid`, and
it does block every later namespace or key operation.

**File hand-off.**
- **Tree, `seat-home` and `seat-out`.** Chowned to n inside H (step 3), so the seat writes
  there as their owner.
- **Bundle, instructions and agy image.** Sealed memfds bound 0444 or 0555. No host file is
  involved.
- **Token pipe.** The parent creates it and passes it by fd. An fd survives the uid change, so
  no permission change is needed.
- **Parent reads.** Files the seat creates may be 0600 and owned by n, and the operator cannot
  read them from outside H. So the J10 reader runs **inside H as H-root**, with
  `CAP_DAC_READ_SEARCH` in H only. It follows the same fd-relative no-follow, regular-file and
  size-cap rules, and it streams the bytes to the parent over a pipe.
- **Gemini re-inject and teardown.** Both run in the same in-H helper. The re-inject renames a
  new copy into `gemini-config/`, owned by the operator with group n and mode 0440. Teardown is the J2 fd-relative walk, run before H
  exits. If teardown fails, the directory is never deleted by following links. It is kept,
  and the leg carries `seat_sandbox_retained_after_teardown`, which names the retained path.
  - The retained directory may hold anything the seat wrote, its token included, so it stays
    owned by the seat uid and unreadable to other local users.
  - **F020.** Every retained directory sits under the leg's `mkdtemp` scratch directory,
    which is owned by the operator and mode 0700, so no other local user can reach it.
  - `phase-loop seat-sandbox reap` removes it later. It builds a new mapped namespace through
    the same `newuidmap` path and runs the same fd-relative teardown.
  - **F022.** `reap` accepts only a path recorded by a retention notice, under the stage
    root, opened `O_NOFOLLOW|O_DIRECTORY` one component at a time, and owned by a
    subordinate uid. Anything else is refused, and a falsifier proves each refusal.

**Launcher integration.** These are the named `panel_invoker.py` sites:
- `_compose_launch_prefix` composes the D8 order above for a `SeatJail` owner. It replaces the
  agent-harness#1109 switch on this route only; every other route is unchanged.
- `_provider_launch_prefix` omits `env --chdir=<host path>` under a jail.
- `_ReviewMonitor.owned_command` uses the jail owner on the tooled Gemini profile.
- `_require_seat_identity` runs through the jail prefix. Its expectations are J6 and J15:
  - the seat ids;
  - capabilities 0 and `CapBnd` 0;
  - `NoNewPrivs` 1;
  - `Seccomp` 2 with the production filter digest;
  - mountinfo equal to J1;
  - the fd set equal to the declared set;
  - an invisible host `/tmp` marker.

`sandbox_egress.isolated_network` gains the unmapped-holder variant used by this route; that is
a named site.

**Keyring.** The first element of the jail prefix is a small packaged exec shim,
`python -m phase_loop_runtime.seat_keyring_exec`, run with the runtime's absolute interpreter.
It calls `keyctl(KEYCTL_JOIN_SESSION_KEYRING, NULL)` through the syscall and then execs the
rest of the prefix. No keyutils binary is required.

**Host versus jail paths.** Validation takes host paths. The argv, the cwd and the transcript
slug use jail paths. `provider_cwd_sha256` attests `/seat/tree` together with the profile
digest.

### Secrets: the Claude seat token

- **Storage.** The token lives at `$XDG_STATE_HOME/phase-loop/seat-credentials/claude`:
  - the file is 0600 and the directory 0700, both owned by the euid;
  - it is opened `O_NOFOLLOW` and checked with `fstat`;
  - a failed check gives `seat_sandbox_refused:token_file_unsafe`.
- **Delivery.** The only channel is one pipe.
  - The parent writes the token into the pipe and closes the write end.
  - The read end is the only extra fd passed to the leg, named by
    `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`.
  - Once the CLI has drained the pipe, reopening the fd yields nothing.
  - There is no file and no mount. `_broker_subscription_env` is unchanged.
- **Redaction.** The argv shape, the environment keys and the evidence carry a fixed
  placeholder for the fd. Before seat output is stored or published, the parent scans it for:
  - the token bytes;
  - their standard, URL-safe and hex encodings at every alignment.

  A match refuses the leg with `claude_seat_token_in_output`. Split or transformed forms can
  still pass, and D3 says so.
- **Authentication proof.** The jailed route calls `seat_jail.claude_seat_token_ready()`
  instead of `_claude_subscription_auth_ok`. The P2 rejection signature maps to
  `claude_seat_token_rejected`.

### Claude seat inside the jail

`_broker_claude_tui_command` keeps its default output, so the president and the sealed route
are unchanged. `sandboxed: SeatJail | None = None` selects this argv:

```
/seat/bin/claude --ax-screen-reader --safe-mode --no-chrome --disable-slash-commands
  --model <m> --session-id <uuid> <effort args>
  --setting-sources "" --settings '{"apiKeyHelper":""}' --strict-mcp-config
  --mcp-config '{"mcpServers":{}}' --agents '{}'
  --permission-mode bypassPermissions --tools default
```

- **Private config.** `CLAUDE_CONFIG_DIR=/seat/home/.claude`. The pre-seed contains exactly
  the P1-pinned keys. It is written fd-relatively (J10) into the fresh `seat-home`. The
  operator's `~/.claude*` is never mounted (agent-harness#1104).
- **Modals.** The detector stays armed and never answers. A modal refuses the leg with
  `claude_tui_workspace_trust_blocked` or `claude_seat_bypass_ack_blocked`.
- **Transcript and output.** `_claude_project_dir_for_cwd` gains a `config_dir` argument.
  `_run_claude_tui_session` reads the transcript and `seat-out/panel-claude.txt` only through
  the J10 reader.

### Gemini (agy) seat inside the jail (D7; gated on P4 then P3)

Until P4 and P3 pass, the Gemini seat runs the sealed route, which is golden-identical to
today. It never uses the full operator credential inside a jail.

**The D7 credential outcomes.** Every outcome is typed, and none falls back to the full file.

| outcome | route and code |
|---|---|
| operator file missing | sealed route, `gemini_seat_credential_missing` (today's sealed behaviour) |
| operator file a symlink, wrong owner, too loose, over the cap, unparseable, or no `access_token` | leg refused, `seat_sandbox_refused:gemini_credential_unsafe` |
| P4 stop: copy unusable, agy refreshes in-jail, or config dir must be writable | sealed route, `gemini_seat_credential_unusable` |
| P4 stop: token scopes go beyond inference | sealed route, `gemini_seat_token_scope_excess` |
| P3 stop: event split or workspace config | sealed route, `gemini_seat_stream_split_unavailable` |
| remaining lifetime below the P4 floor at launch, with no working outside refresh | leg refused, `gemini_seat_token_expired` |
| mid-leg expiry, re-inject path: refresh fails, rename fails, deadline missed, or provider rejects after injection | leg ended, `gemini_seat_token_expired` |
| mid-leg expiry, end-typed path | leg ended, `gemini_seat_token_expired`. The P4 expiry signature maps to it **before** the default-deny stream rule. |
| copy bytes in seat output | leg refused, `gemini_seat_token_in_output` |

**Mechanics.**
- The copy is built on the host from an `O_NOFOLLOW` read with an `fstat` owner check and a
  size cap.
- It is written only into `gemini-config/`, which the parent builds. The in-H hand-off leaves
  it owned by the operator, with group n and modes 0750/0440. That directory is bound read-only **as a directory** at the config path P4
  recorded. Every ancestor of that path is on the read-only
  root.
- **P4 chooses between re-inject and end-typed.** P4 selects re-inject only if both of these
  hold: agy picks up a copy renamed into the bound directory mid-session, and the pinned
  outside refresh works. Otherwise the leg ends typed at expiry.
- Re-injection uses the P4-pinned outside refresh. It then writes the new copy to a temporary
  name in `gemini-config/` and `rename`s it over the old one, through the in-H helper. This is the mechanism P4
  exercised, and it is visible through the directory bind.
- The refresh helper runs outside the jail with the pinned argv, an empty 0700 cwd, stdin
  `/dev/null`, no workspace, no tools and no inference.
- `gemini-config/` is deleted at round end.

**Profile.**
- `agy_memfd_seat_jail_tools_v1` is added beside the unchanged deny-all profile.
- The argv adds `--add-dir /seat/tree` and `--dangerously-skip-permissions`, and drops
  `--mode plan`. bwrap adds `--new-session`.
- The settings are the P3 values, with every P3-recorded workspace loader disabled.
- The stream check is default-deny, with one mapping first: the expiry signature becomes
  `gemini_seat_token_expired`. Recorded tool events pass. Subagent events and unknown events
  are refused with `gemini_seat_subagent_or_unknown_event`.
- The tooled profile runs only on images whose qualification record covers it. Otherwise the
  seat takes the sealed route with `gemini_seat_profile_unqualified`.
- Both 1.2.11 and 1.2.12 are requalified on the final tree.
  - The packaged driver `agy_qualification.py` is extended to the tooled profile.
    `qualify_gemini_heartbeat.py` stays a shim over that driver.
  - Main's `ROUTE_CORE` is `("gemini_heartbeat.py", "agy_qualification.py", "agy_provenance.py")`,
    from agent-harness#1130. L3's edits to `gemini_heartbeat.py` and `agy_qualification.py`
    therefore change route-core, and the requalification records must pass
    `verify_qualified_agy_image.py --route-core` on the final tree.

### Pointer briefs

Only jailed seats receive a pointer brief. It contains:
- the sandbox preamble, for jail paths;
- the AUTHORITATIVE INSTRUCTIONS frame, inline;
- a POINTER frame naming `/seat/review/review-bundle.md` (the sealed-memfd bytes, with sha256
  and size), and `/seat/tree` with the authorization's source commit and `staged_tree_sha256`.

**Integrity checks:**
- The bundle and instructions are sealed memfds, so neither the seat nor another same-uid
  process can change them.
- Before exec, the parent re-hashes the tree with the J10 walk and compares the digest with
  the authorization.
- A test proves this walk gives the same digest as the existing staged-tree revalidation on a
  tree without links.
- A mismatch refuses the leg with `seat_sandbox_refused:stage_changed`.

The evidence records `provider_input_mode: "pointer"`, `provider_input_inline: False` and the
digests.

### Typed notices

A notice is `{code, seat_key, what, why, fix}`, rendered only from literals. It is delivered
on three surfaces:
- the `advisor-board` payload (`notices`, `legs[].notices`);
- the text summary;
- **the governed path**. Governed rendering is lane L4b, which edits `governed_review.py`
  after agent-harness#1071 lands, so the two do not overlap in time.

A notice that ends a leg is also its `detail`. Every code, including each sub-code, joins the
closed vocabulary, and each code has a delivery test on all three surfaces.

| code | when | what / why / fix |
|---|---|---|
| `seat_sandbox_unavailable_host` | J7 step 2: no userns, slirp4netns or bwrap | inline fallback / host capability missing / install them, enable unprivileged userns |
| `seat_sandbox_unavailable_seat_uid` | J7 step 2: no setuid `newuidmap`/`newgidmap`, no subordinate range, range exhausted, or operator uid 0 | inline fallback / no subordinate seat uid on this host / root once: `apt install uidmap` and `usermod --add-subuids/--add-subgids` for the operator |
| `seat_sandbox_unavailable_tiocsti` | J7 step 2: `legacy_tiocsti` ≠ 0 or absent | inline fallback / host allows keystroke injection / kernel ≥ 6.2 and `dev.tty.legacy_tiocsti=0` |
| `seat_sandbox_not_staged` | J7 step 0, no staged tree authorized | inline fallback / caller requested no tree / pass a staged-tree authorization |
| `seat_sandbox_refused:jail_build` | J7 step 5, including the seccomp filter | leg refused / jail setup failed / report a defect |
| `seat_sandbox_refused:namespace` | J7 step 5 | leg refused / namespace setup failed / check slirp4netns |
| `seat_sandbox_refused:identity` | J7 step 5, jailed route | leg refused / seat not provably confined (seat ids, capabilities, mountinfo, fd set, filter digest, or no EC-EXECFIND-2 pass for this jail digest) / report a defect |
| `seat_sandbox_refused:preseed` | J7 step 5 | leg refused / seat-home not writable / check disk |
| `seat_sandbox_refused:token_file_unsafe` | J7 step 5, Claude token file | leg refused / seat-token file not owner-only / `chmod 600`, dir 700, own it |
| `seat_sandbox_refused:gemini_credential_unsafe` | J7 step 5, operator agy file | leg refused / operator agy credential file unsafe or unreadable / fix owner, mode, or re-login agy |
| `seat_sandbox_retained_after_teardown` | the in-H teardown failed after the leg | directory retained / teardown could not remove seat-owned files, which may include the seat token / run `phase-loop seat-sandbox reap`; revoke the seat token if the leg is suspect |
| `seat_sandbox_refused:stage_not_private` | J7 step 5, staged tree has a hard-linked entry | leg refused / staged tree shares an inode with a file outside the stage / re-stage; report a defect in staging |
| `seat_sandbox_refused:stage_changed` | pre-exec tree re-hash mismatch | leg refused / staged tree changed / re-run |
| `seat_sandbox_refused:output_unsafe` | J7 step 6 | leg rejected / seat tampered with its output / none |
| `seat_sandbox_egress_opt_out` | opt-out variable set | ran unfiltered / operator opt-out / unset it on a capable host |
| `seat_sandbox_root_fell_back` | `sandbox_root_fell_back` | staged on fallback root / configured root unreachable / fix the root |
| `seat_sandbox_root_unapplied` | `sandbox_root_applied=False` (agent-harness#896) | staged locally / remote co-location not implemented / none yet |
| `seat_staging_below_floor` | existing floor refusal | leg refused / disk / free space |
| `seat_filesystem_unconfined` | tooled Codex or grok launch | seat can read and write operator files and jailed seats' host directories / not jailed yet / agent-harness#895 follow-up |
| `seat_tool_denied` | agy `tool_denied` template | tool use denied / agy auto-denied a tool / on the tooled profile a defect; on the sealed route expected |
| `claude_seat_token_missing` | J7 step 3 | inline fallback / no seat credential / run `claude setup-token`, store it as documented |
| `claude_seat_token_rejected` | P2 rejection signature | leg ended / revoked or expired / re-run setup |
| `claude_seat_token_in_output` | J7 step 6 | leg rejected / seat tried to publish its credential / revoke the token |
| `claude_seat_bypass_ack_blocked` | modal appeared | leg refused / pre-seed stale for this CLI / upgrade runtime |
| `claude_tui_workspace_trust_blocked` | existing, trust modal appeared | leg refused / pre-seed stale for this CLI / upgrade runtime |
| `gemini_seat_credential_missing` | J7 step 3, operator agy file absent | sealed route / agy not logged in / log in to agy |
| `gemini_seat_credential_unusable` | J7 step 1, P4 stop | sealed route / agy cannot run tooled on the stripped credential / none until agy changes |
| `gemini_seat_token_scope_excess` | J7 step 1, P4 scope stop | sealed route / the stripped agy token's scopes go beyond inference / maintainer ruling on the measured scopes, then re-run P4 |
| `gemini_seat_stream_split_unavailable` | J7 step 1, P3 stop | sealed route / agy tool and subagent activity or workspace config cannot be controlled / none until agy changes |
| `gemini_seat_profile_unqualified` | J7 step 4 | sealed route / image not qualified for the tooled profile / requalify |
| `gemini_seat_token_expired` | D7 table | leg ended / short-lived seat credential expired / re-run |
| `gemini_seat_token_in_output` | J7 step 6 | leg rejected / seat tried to publish its credential / none; the copy expires on its own |
| `gemini_seat_subagent_or_unknown_event` | J7 step 6 | leg ended / subagent or unrecorded agy activity / none |
| `native_seat_unavailable_heartbeat_only` | existing `native_fill_requested` and `president_fill_heartbeat_refused` refusals | seat not filled / heartbeat cannot bind a native fill / run bounded, or accept the brokered seat |
| `under_claude_code` | existing | seat deferred to the driving session / nested TUI unavailable / fill natively or run from a plain shell |
| `seat_prompt_over_cap` | inline prompt over `_BROKER_SEALED_PROMPT_MAX_BYTES` | leg refused / inline fallback cannot carry this bundle / run where a jail is available |
| `seat_identity_unverified` | `SeatIdentityUnverified`, unjailed route only | leg refused / seat not provably the operator, locked down / report a defect |

## Maintainer decisions (recorded 2026-09-28 on agent-harness#1132)

The maintainer ruled D1 through D8 on 2026-09-28, recorded on agent-harness#1132. Each is
binding on this plan and names what enforces it.

- **D1 Jail Claude and Gemini now; Codex and grok follow under agent-harness#895.** Until
  then, Codex and grok carry `seat_filesystem_unconfined`. Gemini is gated on P4 and P3.
  Enforced by: "Seat jail", J1–J4, J7.
- **D2 Claude uses a dedicated `claude setup-token` seat token.** It is stored owner-only and
  delivered by one drained pipe fd. The operator's primary login never enters the jail. With
  no token, the seat takes the sealed route with `claude_seat_token_missing`.
  Enforced by: "Secrets", J3, J7.
- **D3 EC-HARDEN-5 is UNMET for tooled seats, with an accepted residual under
  agent-harness#361.** The recorded residual states the following:
  - **Claude.** A jailed Claude seat can:
    - read its own seat token from the fd;
    - pass it to processes it creates and write it to files it creates;
    - reuse it for the token's lifetime (P2);
    - exhaust the shared subscription;
    - send it out over public egress, including in split or transformed forms that the output
      scan misses.

    Revocation is documented in the capabilities card.
  - **Gemini.** A jailed Gemini seat can do the same with its D7 access token, for that
    token's remaining lifetime and within the scopes P4 measured. It cannot obtain a refresh
    token.
  - **Unjailed Codex and grok.** Until the agent-harness#895 follow-up, they run as the
    operator's uid. They can:
    - read the operator-owned seat-token file;
    - read, but not write, whatever a jailed seat leaves world-readable in its seat-uid-owned
      directories;
    - read whatever their own `/proc` exposes.

    Because a jailed seat now runs as a different uid (D8), the operator's uid can no longer
    write those directories.
  - **World-accessible operator objects.** The seat has an unrelated local uid's access
    (J3), so any key or other kernel object the operator made "other"-accessible stays
    usable. An example is an AF_ALG keyed operation by serial, through an io_uring-created
    socket. Any local user can already do the same.
  - **Resource exhaustion.** Fork bombs, disk through `/seat/home` and RAM through tmpfs are
    not bounded beyond the existing leg deadline.

  The other HARDEN protections hold, as described under "EC-HARDEN-5".
- **D4 The EXECFIND scoping is a separate amendment, agent-harness#1134.** It lands before
  this implementation merges.
- **D5 A host with no sandbox capability, or unsafe TIOCSTI, takes the sealed route with a
  notice.** Capability is decided once, before staging (J7 step 2).
- **D6 The tool set is `--tools default`.** MCP is empty, no user or project settings load,
  and skills are disabled. For agy, only recorded tool events pass, and workspace loaders are
  disabled (P3).
- **D7 The Gemini seat credential is a short-lived copy (recorded 2026-09-28).** It is an
  access-token-only copy of the operator's `antigravity-oauth-token`, with `refresh_token`
  removed.
  - P4 shows agy runs with it and measures the token's lifetime.
  - A leg that outlives the token is either re-injected from outside the jail or ends with
    `gemini_seat_token_expired`.
  - If P4 fails, Gemini stays sealed and never falls back to the full credential.
  - Every credential outcome is typed in the D7 table.
  - L3 is unblocked, on condition that P4 passes.

  Enforced by: the Gemini section, P4, J3, J7.

- **D8 The jailed seat runs under a subordinate uid (recorded 2026-09-28 on
  agent-harness#1132).** It uses uidmap with subuid and subgid ranges. In-namespace uid 0 is
  the operator, and the seat runs as a leased subordinate uid with no capabilities.
  - The J14 key denial stays as defence in depth.
  - A host without the prerequisite takes the sealed route with
    `seat_sandbox_unavailable_seat_uid`.
  - The root setup is a maintainer prerequisite on each host, and is never run by the runtime.

  Enforced by: "Seat uid", J6, J15, J7 step 2, P5.

## EC-HARDEN-5 on the now execution-capable routes

EC-HARDEN-5 is cited by ID. The authorization clauses hold unchanged:
- A fresh operation-bound authorization comes before the first effect, and `invoke_board`
  revalidates it.
- The capability probe spawns `unshare`, so it runs only after the public-entry authorization
  is validated.
- The local authorization revalidation in `_default_spawn` runs after staging, as today, and
  before the namespace, jail, pre-seed, token read and Gemini copy.
- Tests prove none of these is reachable from a pure control or an unauthorized call.

The mutation clause holds by construction. The only writable repository is the disposable
clone, which has no remote credentials and no mounted origin, and is deleted at round end.

The credentialed-side-effect clause is the D3 residual. It is recorded, not claimed as met,
and J8 makes the verifier report it.

## EC-EXECFIND-2 obligations on the jail

Merged agent-harness#1134 amended EC-EXECFIND-2; it is cited here by ID and not restated. It
puts two obligations on this plan:
- **Jail identity.** The jail identity a dispatch record carries is `seat_jail`'s profile
  digest, which covers the mount set, the flags and the J14 filter digest. `_default_spawn`
  writes that identity into the dispatch record only after EC-EXECFIND-2's jail falsifiers
  have passed against that exact digest. The pass is recorded as evidence keyed by the digest.
  A seat whose jail digest has no recorded pass is never put on the jailed route. It is refused
  before launch with `seat_sandbox_refused:identity` (J7 step 5).
- **Who runs the falsifiers.** This plan's landing runs EC-EXECFIND-2's jail falsifiers against
  the shipped jail, using the real falsifier-run layout from agent-harness#1071. Any change to
  the jail profile digest, or to EXECFIND's staging, invalidates the recorded pass until they
  are re-run.

## Changes

| File | Action |
|---|---|
| `phase_loop_runtime/seat_jail.py` (new) | `SeatJail`, `build_seat_jail`, `seat_sandbox_capable`, mount set, profile, pre-seed, token pipe, `claude_seat_token_ready`, D7 copy and re-inject, J10 reader and tree walk, output scan, the J14 seccomp BPF builder, notice helper. |
| `phase_loop_runtime/seat_keyring_exec.py` (new) | Join a fresh session keyring, then exec. |
| `phase_loop_runtime/seat_uid.py` (new) | Subordinate-range discovery, seat-id lease, `newuidmap` and `newgidmap` driver, in-H hand-off, reader, teardown and reap helpers. |
| `phase_loop_runtime/sandbox_egress.py` | Unmapped-holder variant for the seat-uid route; every other route is unchanged. |
| `phase_loop_runtime/panel_invoker.py` | Named sites only: `sandbox_usable_by` (per-launch jail fact); `_compose_launch_prefix`; `_provider_launch_prefix`; `_ReviewMonitor.owned_command`; `_require_seat_identity`; `_broker_claude_tui_command` (`sandboxed=`); `_exec_claude_tui_leg`; `_claude_project_dir_for_cwd`; `_run_claude_tui_session` (reads); `_brokered_gemini_command` (heartbeat branch, after P4 and P3); `_broker_tool_controls`; `_render_broker_inline_prompt` (pointer); `_default_spawn` (J7 order, memfd bundle, re-hash); vocabulary codes. |
| `phase_loop_runtime/gemini_heartbeat.py`, `phase_loop_runtime/agy_qualification.py` (route-core under agent-harness#1130's `ROUTE_CORE`, L3) | Tooled profile, directory-bound config, stream split, driver support for the tooled profile, requalification. |
| `phase_loop_runtime/governed_review.py` (L4b, after agent-harness#1071) | Render notices on the governed path. |
| `phase_loop_runtime/cli.py` | `notices` in the payload and text summary; `phase-loop seat-sandbox reap`. |
| `scripts/verify_harden_evidence.py` | Pointer mode, jail facts, EC-HARDEN-5 UNMET reporting. |
| `plans/evidence/` | P1–P5 records and mutation receipts; agy requalification (L3). |
| `advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md` | Contract, token setup and revocation, notices. |
| `tests/test_seat_jail.py`, `tests/test_seat_sandbox_permissions.py`, `tests/test_seat_notices.py` (new) | Falsifiers. |

`review_summary.py` and `_broker_subscription_env` are not touched.
- agent-harness#1130 has landed (`f9d9726a`). Its `panel_invoker.py` hunks
  (`president_findings_from_legs`, `_preflight_gemini_heartbeat` and `invoke_board`) are
  part of main and are not named sites.
- **F030.** `_HARNESS_DETAIL_CODES` IS a named site: every leg-ending code joins it as an
  exact literal (each `seat_sandbox_refused:<sub>` separately), with no regex template and
  no parallel vocabulary. The delivery test asserts that `legs[].detail` equals the literal
  after `_finalize_leg_detail`; dropping one code from the set turns it red.
- At the time of writing, the open agent-harness#1071 changes these `panel_invoker.py` hunks:
  `PanelLegResult.usable`, `attach_native_agent_request`, `terminal_verdict` and
  `_president_ruling_complete`. None of these is a named site either.

At rebase, re-check the #1071 hunks, together with `_ReviewMonitor.owned_command` and
`_default_spawn`.

## Lanes and ownership

- **L0 probes and tests first.**
  - Run P1 and P2. After P4, run P3. Pin the evidence digests, then apply the stop rules.
  - Add every falsifier below, skip-guarded on its implementing symbol, and record a RED
    receipt against an existing stub. The stub receipt only proves the test exists and is
    wired. It is **not** mutation evidence.
- **L1 `seat_jail.py`, `seat_uid.py`, `seat_keyring_exec.py` and the launcher sites.** Starts
  after P5, P1 and P2 are pinned.
- **L2 Claude.** Starts after L1.
- **L3 Gemini.** Starts after L1, P4 and P3. Its agent-harness#1130 dependency is satisfied,
  because #1130 landed as `f9d9726a`.
- **L4 Pointer briefs, evidence, notices (payload and summary) and docs.** Starts after L2,
  and after L3 if L3 is in scope.
- **L4b Governed-path notice rendering.** Starts after agent-harness#1071 lands.
- **Mutation receipts, in every lane.** When a lane lands a control, it records two receipts
  against the **real module path**:
  - the falsifier green on the unmutated code;
  - the falsifier red with the named mutation applied, together with the mutation diff.

  Both are recorded again at the final head. A mutation that stays green blocks the lane.
- **Host prerequisite (maintainer, root).** Before P5 and before L5 or the live board on a
  host: `apt install uidmap`, then `usermod --add-subuids` and `--add-subgids` for the
  operator. The runtime and the lanes never run these.
- **L5 live.** Replay the probes that were reached, and any recorded stop, on the final
  candidate. Run the boards in "Acceptance". Requalify agy for both the sealed and, if L3
  is in scope, the tooled profile, and require `verify_qualified_agy_image.py --route-core`
  to exit 0 on the final tree (F035).

Everything lands in one implementation PR. agent-harness#1134 and agent-harness#1130 have
already landed, so the PR waits only for agent-harness#1071.

## Tests and falsifiers

Every falsifier is a live test on the shipped module. Each has a named mutation, and each
mutation has control and red receipts ("Lanes"). Canaries sit at host-absolute paths created
by the parent. Where success is observed, the parent observes it.

**One rule for every falsifier: the fixture isolates the layer it tests.**
- A falsifier's fixture disables every *other* layer that would refuse the same action, so the
  named mutation can go red.
- Each falsifier states which layers its fixture disables. The usual fixture is **same-uid**:
  the seat runs as a uid that DAC and the kernel's uid checks would let through, or both seats
  lease the same uid.
- Each layer's end-to-end refusal in the production configuration is kept as a separate live
  check, and a live check never demands success after one layer is removed.
- Canary files are mode 0644 wherever the seat's uid must not be what refuses the read.

- **J1.**
  - Mountinfo equals the declared set.
  - `cat` fails for each canary: in `$HOME`, in `$HOME/.ssh`, in `/mnt/workspace`, in the live
    repo, and in `/run/user/<uid>`.
  - Fixture: canaries at mode 0644 in world-searchable directories, so that DAC does not refuse
    the read.
  - Mutation: `--ro-bind "$HOME" "$HOME"`.
- **J1, Gemini config.** Two layers protect the config directory, and each is proven
  separately:
  - **Read-only bind layer.** Fixture: the directory is group-writable by n (0770/0660), so
    permissions would allow the write. Writing and renaming inside it fail with EROFS.
    Mutation: bind the directory read-write, or place it under `/seat/home`. The write then
    succeeds.
  - **Permission layer.** Fixture: a test-only read-write bind with the production ownership
    (operator, group n, 0750/0440). Writing and `chmod` both fail with EACCES or EPERM.
    Mutation: grant group write (0770/0660). The write then succeeds.
  - **Production, end to end.** Writing, renaming and `chmod` all fail. Renaming an ancestor
    fails on the read-only root. Overmounting an ancestor is covered by J14.
- **Teardown retention.** A fault is injected so the in-H teardown fails.
  - The leg carries exactly one `seat_sandbox_retained_after_teardown` notice, on all three
    surfaces.
  - The retained directory is still owned by the seat uid, and `reap` removes it.
  - Mutation: swallow the teardown error. The notice is then missing, so the test goes red.
- **J2.**
  - `touch /x`, `/etc/x`, `/usr/x` and `/seat/review/x` all fail.
  - A host sentinel directory stays empty. Same-uid fixture: the sentinel directory is owned
    by the seat uid, so DAC would allow the write.
  - Teardown does not follow a planted link to an outside canary.
  - Mutations, one per check:
    - bind the sentinel directory read-write, which reddens the sentinel check;
    - drop `--remount-ro /`, which reddens `touch /x`;
    - replace the teardown with a link-following `rmtree`, which deletes the canary.
- **Hard-link hand-off.**
  - Setup: the parent plants, in the staged tree, a hard link to an operator-owned 0600 file
    outside the stage.
  - The hand-off refuses the leg with `stage_not_private`, and the outside file's owner and
    mode are unchanged.
  - Mutation: skip the nlink check. The outside file's owner becomes the seat uid, which
    reddens the test.
- **J3, credential channels.**
  - **Environment.** The in-jail `env` equals the declared set. Mutation: drop `--clearenv`.
  - **Descriptors.** `/proc/self/fd` equals the declared set. Mutation: leak the broker socket
    fd through `pass_fds`.
  - **Operator-owned keys, by serial (J15, D8).**
    - **Setup.** The parent creates two operator-owned objects, each with owner permissions
      (view, read and search) set and possessor, group and other permissions **off**:
      - a `user` canary key;
      - a keyring that contains the canary.

      It passes both serials into the jail.
    - **Assertions.** From the seat, each of these fails:
      - `KEYCTL_READ` on the key;
      - `KEYCTL_SEARCH` rooted at the **keyring**, for the canary's description;
      - an AF_ALG keyed hash (`hmac(sha256)` with `ALG_SET_KEY_BY_KEY_SERIAL`) on the key, with
        the AF_ALG socket created both directly and through io_uring (`IORING_OP_SOCKET`).
    - **Mutation.** Run the seat under the **operator** uid (the agent-harness#1109 mapping),
      with the **test-only filter variant** that lacks the key and AF_ALG rules. This fixture
      disables the filter layer. The read, the search and both keyed hashes then succeed, so
      the uid layer is falsifiable on its own.
    - **Other-grant residual, recorded rather than hidden.** The same fixture with "other"
      read and search set shows that the seat-uid launch *can* use that key through an
      io_uring AF_ALG socket. The evidence records that the D3 "world-accessible" residual
      holds as stated.
    - **Filter is unreachable in production.** The variant has its own digest, and J6 refuses
      any launch whose filter digest is not the production digest. A J6 mutation tries to
      install the variant.
    - **The production filter layer** is proven separately, in J14's interpreter proof.
  - **Session keyring.** This check runs under the test-only variant and an operator-uid seat,
    so that neither the filter nor the uid masks it.
    - **Control.** With `seat_keyring_exec`, the seat's `@s` serial differs from the parent's,
      and a canary with possessor-read in the parent's `@s` cannot be read.
    - **Mutation.** Skip the shim. The fixture then asserts that the seat's `@s` serial
      **equals** the parent's, showing the keyring really is shared, and the canary read
      succeeds.

    The old user-keyring and "drop `--unshare-user`" tests are removed. Unprivileged bwrap
    always creates a user namespace, so that mutation could not share `@u`. Uid-owned keys are
    now covered by the serial test above.
  - **Harness surfaces.** With a sentinel token, no harness-constructed argv or environment
    (bwrap and the provider, read at launch before seat code runs) and no evidence, log, leg
    record, board payload or published text contains the token or its scanned encodings.
    Mutations: `--setenv CLAUDE_CODE_OAUTH_TOKEN <tok>`, or disable the output scan.
- **J3, Gemini.**
  - The in-jail credential has no `refresh_token` and matches the declared copy. Mutation:
    bind the operator's file.
  - An expired copy with no working outside refresh ends the leg with
    `gemini_seat_token_expired`, and no launch uses the full file. Mutation: fall back to the
    operator's file.
  - A failed re-inject refresh ends the leg with `gemini_seat_token_expired`. Mutation: retry
    without the copy.
  - The expiry signature is reported as `gemini_seat_token_expired`, not as an unknown event.
    Mutation: remove the mapping.
  - Each operator-file hygiene failure in the D7 table refuses the leg with
    `gemini_credential_unsafe`. Mutation: proceed without the check.
- **J4.** Seats A and B run concurrently. Each writes sentinels into its own directories, binds
  an abstract socket and starts a sleeper. The parent passes B the **host** pids of A's
  processes and the host paths of A's directories. B's attempts must all fail:
  - read A's files through B's own aliases and through A's host paths;
  - connect to A's socket;
  - read `/proc/<A host pid>/environ`;
  - `kill -0` A's sleeper;
  - `ptrace(PTRACE_ATTACH)` A's sleeper.

  In production, A and B have different seat uids, so every attempt above is also refused by
  DAC or by the kernel's uid checks. That end-to-end refusal is the live check. The per-layer
  mutations use fixtures:
  - **Files.** Same-uid fixture: A and B lease the same seat uid. Mutation: shared seat
    directories, after which B reads A's sentinel through its own alias.
  - **Sockets.** Mutation: one shared egress namespace, after which B connects to A's
    abstract socket. The uid split is not a layer for abstract sockets.
  - **PID isolation.** This is checked by a property the uid split cannot mask: A's host pid
    is **not visible** in B's `/proc`, and B cannot read A's world-readable
    `/proc/<pid>/cmdline` or `status`. Mutation: drop `--unshare-pid` and bind the host
    `/proc`. A's pid then becomes visible and its `cmdline` readable, which reddens the test.
  - **Signals, `ptrace` and `environ`.** These are checked on a same-uid fixture, in which A
    and B share a seat uid, with the same PID mutation: `kill -0` and the `environ` read then
    succeed.

  The evidence records Yama's `ptrace_scope`. Under scope 1, `ptrace` stays refused even on
  the same-uid fixture, so the `kill` and `environ` checks are the mutation-sensitive ones
  there. That is stated, not hidden.
- **J5.** Network egress and the broker socket are separate layers, each proven on its own.
  - **Egress layer.** The `sandbox_egress` table, re-run inside the jail, matches. Mutations:
    add `--unshare-net`, which makes the public host unreachable; drop the egress namespace,
    which makes the private CIDR reachable.
  - **Broker socket, mount layer.** A pathname Unix socket is a filesystem object, and network
    namespaces do not scope it. The only layers that matter are the mount set and the socket
    file's permissions. The broker socket is refused because its directory is not mounted.
    - Fixture: a test-only sentinel listener at a `/run`-style path, mode 0666, owned by the
      seat uid, so permissions allow the connect.
    - Production: connecting to that path fails with ENOENT.
    - Mutation: bind its directory into the jail. The connect is then accepted, as the parent
      observes.
  - **Production, end to end.** Connecting to the real broker socket's host path fails.
- **J6 and J15.**
  - P5 and the launch probe show that the provider runs as n with `CapPrm`, `CapEff`,
    `CapInh`, `CapAmb` and `CapBnd` all 0.
  - The identity probe shows the leased seat ids, `CapPrm/CapEff/CapInh/CapAmb/CapBnd` all 0,
    `NoNewPrivs:1`, `Seccomp:2` and an invisible host `/tmp` marker.
  - From the seat, `setuid(0)` fails, and so does writing `/proc/self/uid_map`.
  - A capability probe in H finds no capability.
  - The installed filter's digest, which the jail records and the probe reports, equals the
    production filter digest.
  - Mutations, each naming the assertion it reddens:
    - skip `--bounding-set=-all` in `setpriv`: the probe shows a non-zero `CapBnd`;
    - skip the `setpriv` drop: the probe shows uid 0 in H, with exactly `CAP_SETUID`,
      `CAP_SETGID` and `CAP_SETPCAP` still in `CapPrm` and `CapEff`, and `setuid(0)`
      succeeds;
    - omit any one of the three `--cap-add`s: `setpriv` fails before exec, so the launch
      refuses with `seat_sandbox_refused:identity` and makes zero provider launches (one
      mutation for each capability);
    - add a fourth `--cap-add`, such as `CAP_DAC_OVERRIDE`: the pre-drop capability record
      that P5 pins mismatches, and the launch refuses;
    - bind the host `/tmp`: the host marker becomes visible;
    - omit `--seccomp`: the probe shows `Seccomp: 0`;
    - install the test-only filter variant (see J3): the filter digest mismatches.

    Each mismatch refuses the leg with `seat_sandbox_refused:identity` (J13).
- **J15, DAC as a second layer.**
  - **Setup.** A test-only read-write bind puts an operator-owned 0644 canary file, and an
    operator-owned 0755 directory, into the jail.
  - **Assertion.** Writing the file, and creating an entry in the directory, both fail with
    EACCES, because the files are owned by a different uid.
  - **Mutation.** Run the seat as the operator uid. The write succeeds.
  - **Live-tree check.** A walk of every host-backed mount confirms that nothing writable by
    the seat uid is owned by the operator.
- **J14.** J14 has two kinds of proof, and each has its own acceptance rule.
  - **Filter-level mutation proofs.** These run the exact production BPF bytes in a small
    user-space classic-BPF interpreter against synthetic `seccomp_data`. Every rule has a case
    that the rule decides, and a mutation that removes or weakens that rule changes the
    interpreter's verdict:
    - arch `AUDIT_ARCH_I386` → KILL_PROCESS. Mutation: remove the architecture rule.
    - arch `AUDIT_ARCH_X86_64` with `nr = __NR_unshare | 0x40000000` and args
      `CLONE_NEWUSER|CLONE_NEWNS` → EPERM. The same holds for x32 `clone3`, x32 `keyctl`
      (`KEYCTL_READ`) and x32 `setns`. Mutation: remove the x32 rule. The x32 `clone3` case is
      the witness that the threshold fires before the per-syscall `clone3` rule, which would
      have answered ENOSYS instead of EPERM.
    - native `unshare` and `clone` with `CLONE_NEWUSER` or `CLONE_NEWNS` → EPERM.
    - `setns` with `nstype == 0` → EPERM. Mutation: condition the rule on flags.
    - `clone3` → ENOSYS.
    - `keyctl`, `add_key` and `request_key` → EPERM.
    - `socket(AF_ALG, …)` → EPERM, while `socket(AF_INET, …)` and `socket(AF_UNIX, …)` → ALLOW.
      Mutation: remove the AF_ALG rule.
    - `ioctl` with low half `TIOCSTI` or `TIOCLINUX` and a nonzero high half → EPERM.
      Mutation: compare all 64 bits.
    - Allowed controls: `read`, `clone` with thread flags, and `ioctl(TCGETS)` → ALLOW.
  - **Live confinement proofs.** These run in the real jail on claw. Each one only has to show
    that the call is refused there. None of them demands that the call succeed when a single
    layer is removed: several layers can refuse the same call, for example
    `legacy_tiocsti=0`, or `TIOCLINUX` not applying to a PTY. The live calls are:
    - native `unshare(CLONE_NEWUSER)`, `unshare(CLONE_NEWNS)` and `clone` with those flags;
    - `unshare -Urm` followed by a tmpfs overmount of a Gemini config ancestor;
    - `setns(fd, 0)`;
    - `clone3`;
    - the key syscalls;
    - a direct `socket(AF_ALG, SOCK_SEQPACKET, 0)`;
    - `ioctl(TIOCSTI)` and `ioctl(TIOCLINUX)`, with and without upper bits set;
    - an i386 `int 0x80`, which must kill the process;
    - an x32-numbered `syscall` (`nr | 0x40000000`), which must return EPERM. Seccomp sees
      the raw number before syscall dispatch, so on claw this is EPERM from the filter, not
      ENOSYS.
  - **One end-to-end mutation.** Where a live mutation is used, it is the one that is sound
    on claw: omit `--seccomp` entirely. The nested `unshare` and the overmount then succeed,
    because nothing else stops them.
- **J7.** Each step has its own test, and each test asserts exactly one code:
  - **Step 2, seat uid.** No `newuidmap`, no subordinate range, an exhausted range, or operator
    uid 0 → `seat_sandbox_unavailable_seat_uid` and the inline route.
  - **Step 0.** An authorization with no staged tree yields `seat_sandbox_not_staged`. Two
    checks back this:
    - on a capable host, a probe-call counter shows zero calls to `seat_sandbox_capable()`
      and to the credential and qualification checks;
    - on an **incapable-host fixture**, the code is still `seat_sandbox_not_staged`, not
      `seat_sandbox_unavailable_host`.

    Mutation: evaluate capability first. The counter becomes non-zero, and the incapable-host
    fixture yields the wrong code.
  - **Step 1.** A recorded P4 or P3 stop on an image with no tooled qualification yields the
    stop's code, not `gemini_seat_profile_unqualified`. Mutation: run qualification first.
  - **Step 2.** An incapable host, or a TIOCSTI setting that is unsafe or absent, takes the
    inline route.
  - **Step 3.** A missing Claude token, or a missing operator agy file on an unqualified image,
    takes the inline route with the credential code, not the qualification code. Mutation: run
    qualification before credential presence.
  - **Step 4.** An unqualified image, with steps 1–3 passing, yields
    `gemini_seat_profile_unqualified`.
  - **Step 5.** Each pre-launch failure yields its code and zero provider launches. Mutation:
    fall back to the inline route.
  - **Step 6.** Each runtime failure yields its code and no fallback launch. Mutation: launch
    the sealed route after a runtime failure.
- **J8 and J9.**
  - The sealed Claude and president argv, the deny-all agy bytes and `provider_input_inline:
    True` stay golden.
  - Pointer evidence verifies only with matching digests.
  - The verifier reports UNMET.
  - Mutations: record `inline` on a pointer launch, or accept a tooled record as MET.
- **J10.** The seat replaces `panel-claude.txt` and the session JSONL with a symlink to a host
  canary, then a FIFO, then an oversized file, then a directory. It also plants a symlink to a
  host canary in `/seat/tree`, and a FIFO.
  - Each output case refuses with `output_unsafe` within a bounded time.
  - The tree walk never opens the canary or blocks on the FIFO.
  - No canary bytes appear anywhere.
  - Mutations: `Path.read_text()` for output reads, or a link-following walk for the tree.
- **J10, re-hash equality.** On a tree without links, the J10 walk's digest equals the
  existing revalidation's. A byte flipped after the brief is written and before exec is
  refused with `stage_changed`. Mutation: skip the pre-exec re-hash.
- **J11.**
  - The in-jail `tty_nr` is never the operator's terminal.
  - A missing or `1` sysctl gives `seat_sandbox_unavailable_tiocsti`.
  - Mutations: spawn without `start_new_session` from a parent that holds a controlling
    terminal, or remove the precondition.
  - The `TIOCSTI` ioctl itself is denied by J14, and J14's test covers it.
- **J12.**
  - Claude plants: a `.claude/settings.json` hook, a skill, an agent, `.mcp.json` and
    `CLAUDE.md`. Each plant writes a sentinel if it loads.
  - agy plants: one per workspace loader that P3 recorded, each writing a sentinel if it
    loads.
  - No sentinel appears.
  - Mutations: drop `--setting-sources ""`; drop `--safe-mode` (`CLAUDE.md` then appears in the
    transcript); remove each agy loader's disabling setting.
- **J13 and notices.** For every row of the notice table:
  - its trigger yields exactly one notice with that code on each of the three surfaces;
  - it is rendered only from literals;
  - CLI text shaped like a code yields none.

  Mutation: emit a second code for one failure.
- **Tool use.**
  - A jailed Claude seat runs `git log -1` and a named test, and quotes the output. Mutation:
    `--tools ""`.
  - If L3 is in scope, a jailed Gemini seat does the same. Mutation: re-add the deny list,
    which yields `seat_tool_denied`.
- **Modals.** The operator's `~/.claude.json` bytes and mtime are unchanged across a live
  run, and no modal is ever answered. Mutation: enable auto-answer on the jailed route.
- **EC-HARDEN-5 authorization.** With no authorization, a forged one or a stale one, the
  capability probe, jail, pre-seed, token read and Gemini copy all record zero effects.
  Mutation: probe capability before public-entry validation.

## Security review

The plan and the implementation each pass a four-vendor board and a president. The focus
areas are:
- J1, J3, J10 and J14 (the seccomp filter);
- J15 and the D8 launch order: the drop from H-root to the seat uid, capabilities left in H,
  the hand-off chown, and the in-H reader;
- the token pipe and redaction;
- the D7 table and re-inject mechanics;
- J7 ordering;
- the J12 agy loaders;
- the D3 residual text.

## Acceptance

- [ ] P5, P1 and P2 are pinned before L1, and P4 and then P3 before L3. P5 runs only after the
  maintainer's host prerequisite is in place. Either no stop fired, or
  each stop fired is recorded with its sealed notice.
- [ ] Every falsifier has control-green and mutation-red receipts against the shipped module,
  recorded in its lane and again at the final head. At PR head, `automation.suite_command`
  passes on a sandbox-capable host. Only the tooled-Gemini tests may skip, and only if a P4 or
  P3 stop is recorded. In that case the tests proving the sealed Gemini fallback, and proving
  that no tooled or full-credential Gemini launch occurs, must pass.
- [ ] The J9 goldens are green.
- [ ] L5 live:
  - **If L3 is in scope:** a four-seat board with jailed Claude and jailed Gemini, each with a
    pointer brief and a quoted executed check. Codex and grok are on their current routes with
    `seat_filesystem_unconfined`.
  - **If L3 is not in scope:** the same board, with Gemini sealed and carrying its stop notice
    (J7 step 1). The board run must also show that no tooled Gemini launch and no
    full-credential Gemini launch occurred. P3 is replayed only if P4 passed.
  - A forced no-sandbox board showing `seat_sandbox_unavailable_host`.
  - agy requalified for the sealed profile, and for the tooled profile if L3 is in scope;
    `verify_qualified_agy_image.py --route-core` exits 0 on the final tree (F035).
- [ ] The D3 residual text above is recorded in agent-harness#361. agent-harness#1134 has
  landed (merged).
- [ ] EC-EXECFIND-2's jail falsifiers pass against the shipped jail's profile digest, using the
  real agent-harness#1071 falsifier-run layout. The pass is recorded keyed by that digest, and
  a test shows that a dispatch record carries the jail identity only for a digest with a
  recorded pass. Mutation: carry the identity for an unrecorded digest.
- [ ] `CONTRACTS.md` states the jail profile, credential channels, pointer mode and notice
  vocabulary.
- [ ] The plan and the implementation each pass a four-vendor board and a president.

Non-goals:
- Codex and grok jails (the agent-harness#895 follow-up).
- President tooling.
- The SBXEXEC executor.
- Credential-injecting proxies.
- Resource limits beyond the leg deadline (named in D3).
- The parent-held tree-identity half of agent-harness#895.
- Toolchains outside `/usr`.

## Amendment A1 (2026-10-03): the seat uses the Claude login's access token by default

Maintainer decision, 2026-10-03, relayed by the team lead. It **supersedes D2**. D2's text
above is kept as the record of the earlier ruling. Its sentence "The operator's primary login
never enters the jail" no longer holds, and its sealed fallback now applies only when neither
credential source exists.

**Goal.** A user runs the harness, and the jailed Claude seat works on the subscription they
are logged in with. There is no token placement step, and the seat is never silently left
without tools.

**Inputs measured on claw (Claude Code 2.1.288).**
- **The login store:** on Linux, the login lives at `$CLAUDE_CONFIG_DIR/.credentials.json`,
  else `~/.claude/.credentials.json`. The file is 0600. Its `claudeAiOauth` object has the keys
  `accessToken`, `refreshToken`, `expiresAt` (epoch milliseconds), `refreshTokenExpiresAt`,
  `scopes`, `subscriptionType` and `rateLimitTier`.
- **macOS:** the CLI keeps the same JSON in the login Keychain. The generic-password service
  is `Claude Code-credentials`. When `CLAUDE_CONFIG_DIR` is set, the service gets the suffix
  `-<first 8 hex of sha256(config dir)>`. The account is `$USER`. This is read from the CLI
  bundle, and it is tested with a fake, not on a Mac.
- **Windows:** the file store. This is tested with a fake, not on a Windows host.
- **Delivery:** the team lead measured that the CLI accepts the login's short-lived access
  token through `CLAUDE_CODE_OAUTH_TOKEN` in an empty HOME. This amendment's live run measures
  the production fd channel.
- **The refresh trigger:** `claude auth status --json` makes no inference call. Its key set is
  `analyticsDisabled`, `apiProvider`, `authMethod`, `configDirectory`, `email`, `loggedIn`,
  `orgId`, `orgName`, `projectsDirectory` and `subscriptionType`. Whether it refreshes a
  near-expiry token is recorded in the evidence. A refresh is never forced on a copy of the
  store.

**Design.**
1. **Credential source, resolved fresh at each jailed launch.**
   - (a) If the seat-token file exists, it is used. This is an optional override, for example
     to bill another subscription. It is expected to be a long-lived `setup-token`.
   - (b) Otherwise, the current login's `claudeAiOauth.accessToken` is used. Nothing else is
     taken: not the refresh token, not the file, and not the account blob.
   - Both go over the existing drained-pipe channel, and both are output-scanned.
2. **Expiry.** The login token's remaining lifetime must cover a margin. The default margin is
   the leg's deadline. `PHASE_LOOP_SEAT_LOGIN_TOKEN_MARGIN_S` overrides it.
   - **If it is short:** the host runs the CLI's own `claude auth status --json`, never with
     the refresh token and never in the seat, and then re-reads.
   - **If it is still short:** the leg is refused before launch with
     `claude_seat_login_token_expiring` (fix: `claude login`).
   - **An auth failure on a login-sourced leg:** at or past the launch-time `expiresAt` it is
     `claude_seat_login_token_expired`, as both the detail and the notice, and it is safe to
     relaunch with a fresh token. Before that time it is `claude_seat_login_rejected`. An
     override keeps `claude_seat_token_rejected`.
3. **No silent degrading.** Before any seat launches, every board publishes one mode per seat:
   `jailed` (with tools), `sealed` (no tools) or `degraded` (refused before launch). Each mode
   carries its notice code, reason and one-line fix. It is published as `seat_modes` in the
   `advisor-board --json` payload, as one stderr line per seat, and as `seat-modes.json` in the
   stream directory. Post-run notices are unchanged. A host that is jail-capable but has no
   recorded EC-EXECFIND-2 pass now shows `degraded` with
   `seat_sandbox_refused:jail_unqualified` by default, because a login is normally present.
4. **Rate limits by source.** A rate or usage limit is `claude_seat_login_rate_limited` for the
   login and `claude_seat_token_rate_limited` for the override. The reset time stays in the
   leg detail, because notices render only from literals.
5. **Residual.** A seat can use the access token for the token's remaining lifetime, which is
   hours, not a year-long setup token. The response to a suspected leak is to log out and back
   in. The token also expires on its own. This is documented in CONTRACTS and on the card.
6. **General.** Product code carries no fleet paths, pool names or vendor-vault specifics.

**A1 acceptance.**
- [ ] Fakes cover each platform source (Linux, macOS and Windows), the precedence, the expiry
  margin and the refresh trigger, the fail-closed refusal, the preflight mode lines, and the
  mid-run expiry classification.
- [ ] Every new behaviour has a mutation receipt.
- [ ] A live run on claw passes end to end on the login route, with the override moved aside
  and restored.

## Amendment A2 (2026-10-03): the jail is qualified on first use

Maintainer ruling, 2026-10-03, relayed by the team lead. It supersedes A1 item 3's
"`degraded` with `seat_sandbox_refused:jail_unqualified` by default". It also folds in
agent-harness#1186's first-use self-check (option C). That issue's shipped host-independent
policy digest, and its N2 prerequisite, stay open there.

**Rule.** A Claude seat that would take the jailed route, on a host with no EC-EXECFIND-2
pass recorded for this host, jail profile digest and falsifier-run layout, is handled as
follows. A Claude seat is never refused for this.
- **Run once:** the harness runs the host's jail qualification itself, once, before
  launching. It is the same procedure as `phase-loop seat-sandbox qualify`, and on a pass it
  records the pass in the per-host store.
- **Serialized:** an exclusive lock in the per-user state directory serializes the run, so
  concurrent seats and boards run it once and the others wait, then re-read the store.
- **On a pass:** the seat runs jailed with tools, and its mode line reads
  `jailed (qualified now)`.
- **On a failure, or when the run cannot happen** (missing prerequisites, an unsafe store, a
  timeout or an error): the seat takes the sealed route with
  `seat_jail_qualification_failed`. Its mode line names the typed reason (`prerequisite_missing`,
  `store_unsafe`, `falsifiers_failed`, `timeout` or `error`) and that reason's literal fix.
- **The failure cache:** a failure is cached for this host, digest and layout only, so it is
  not retried on every seat. It is retried after `PHASE_LOOP_SEAT_JAIL_QUALIFY_RETRY_S`
  (default 3600 s), or as soon as the digest or the layout changes. A lock timeout is not
  cached.
- **The injected gate:** an injected `pass_recorded` (a test seam) keeps the gate alone, so
  no pass is still `seat_sandbox_refused:jail_unqualified`.
- **The launch-time re-check** against the built jail is unchanged, and still refuses an
  unrecorded digest.
- **In tests:** a suite-wide guard fails any test that would reach a real first-use
  qualification.

**A2 acceptance.**
- [ ] Fakes cover: no record, qualified, then jailed; a failure, then sealed and loud;
  concurrent first use running once; a cached failure not retried until its TTL, digest or
  layout changes; and an existing pass skipping the run.
- [ ] Every new behaviour has a mutation receipt.
- [ ] Live on claw: with the pass record moved aside and restored afterwards, a first-use
  qualification followed by a jailed launch works.

## Round 7 repairs (2026-10-03)

Board round 7 at 34c6cf40. These clarify A1 and A2; they add no new rule.
- **One login margin.** A1's margin "the leg deadline" is the leg's hard deadline before
  staging: its explicit per-leg timeout, else the 1800 s backstop, or
  `PHASE_LOOP_SEAT_LOGIN_TOKEN_MARGIN_S`. The pre-launch seat mode and the launch both get
  it from one function, so A1 item 3's `degraded` mode covers a token that is too short for
  the launch.
- **Credential outcomes are not hidden.** On both routes, an authentication failure named by
  the PTY tail takes priority over the generic journaled give-up
  (`claude_seat_provider_api_error`). Every typed give-up keeps its priority.
- **Launch helpers** run from the trusted package only (`seat_uid.trusted_module_argv`).
- **Fix literal.** The fix line for the login codes is `claude auth login` (Claude CLI
  2.1.288 has no top-level `login` command); this corrects A1's `claude login`.
