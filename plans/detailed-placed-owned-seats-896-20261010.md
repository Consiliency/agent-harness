---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1222, agent-harness#1162, agent-harness#895]
builds_on: [plans/detailed-remote-seat-placement-896-20261010.md, plans/detailed-ssh-placement-backend-896-20261010.md, plans/detailed-seat-launch-factoring-896-20261010.md, plans/detailed-remote-seat-execution-896-20261010.md]
automation:
  suite_command: "cd phase-loop-runtime && PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placed_owned_seat.py tests/test_placed_seat.py tests/test_placement_entry.py tests/test_sandbox_ssh.py tests/test_sandbox_placement.py tests/test_seat_sandbox_permissions.py tests/test_seat_notices.py tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py tests/test_harden_evidence_verifier.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: codex and grok seats run under a leased seat uid on the compute host, then are placed (agent-harness#896, P5)

## Task

After P4 the jailed Claude seat runs on the compute host. Codex and grok do not: on main
they are launched by the seat-launch owner as the **operator's own uid**, on a route main
labels filesystem-unconfined. On a compute host with one shared account, "the operator" is
that account, so such a seat would share a kernel uid with the entry point, its state, and
every other user's codex or grok seat.

The ruling RD3, legs (ii), accepted on 2026-09-29 and still standing, says codex and grok
run on the remote **under a subordinate uid**. The 2026-10-10 ruling "one shared account
first" superseded RD1 (a) only, and was given on the statement that a seat sees only its own
files. This unit implements RD3 (ii): on the compute host a placed codex or grok seat runs
under its own leased subordinate uid, as the Claude seat already does. Only then are those
harnesses placed.

Local launches do not change: a local codex or grok seat keeps today's route and mode.

Cited, not restated: amendments C1–C11 (P1); the entry point, sweep and host qualification
(P2); the credential source (P3); the placed-seat request, result, evidence and mode (P4).

## Research summary

- **The owner route's identity.** `_seat_identity_switch` maps the seat to
  `os.getuid()` / `os.getgid()` and locks its capabilities; `launch_provider` gives the
  bubblewrap owner `--unshare-user --uid <operator> --gid <operator> --cap-drop ALL`. The
  seat's view is `_seat_filesystem_view`: system directories read-only, a private `/tmp`, a
  private home built from memory-backed descriptors, and the declared read-only paths and
  outputs, with pid, IPC and (when filtered) network namespaces. Its launch probe checks
  uid, gid, a marker's owner, capabilities and no-new-privileges; no digest pins its
  argument list, unlike the jail's profile.
- **The jail's identity machinery, reusable as it is.** `seat_uid.lease_seat_id`,
  `subordinate_range`, the unmapped egress holder mapped onto the subordinate range
  (`isolated_network(seat_uid_map=True, required=True)`), `seat_uid.handoff` (hands a
  sandbox's directories to the leased uid through the mapped namespace), and
  `seat_uid.mapped_namespace` for removal.
- **Measured during review of this plan.** A sandbox shaped like the owner route, with its
  pid namespace removed, still fails the three path checks but can signal every process of
  the same uid and reach abstract sockets; with a different kernel uid it cannot signal
  them, and ordinary file permissions protect other users' directories even after a view
  escape. A directory handed to a subordinate uid cannot be removed by the account uid.
- **The prompt names a path.** For a tooled non-jailed seat the launching host renders the
  absolute staged-tree path into the sealed prompt and records the prompt's digest before
  launch. The owner binds each read-only path at the path the arguments name.
- **What each CLI's narrowed login holds** (`_SEAT_CREDENTIAL_SHAPE`, `_access_token_only`,
  `_blank_refresh_token`):
  - codex: its auth file with the refresh token blanked. The access token and the id token
    stay; **in API-key mode the API key stays too**, because the CLI sends no bearer
    without it.
  - grok: its auth file without refresh keys. The bearer is held as `key`, with **no
    lifetime the runtime can read**; plus the agent id file.
- **Not verified here:** where each real CLI keeps the expiry of its access token. The
  default rule is therefore written the safe way round: a token whose expiry the launching
  host cannot read is treated as one that does not expire.
- **The local notice.** `seat_filesystem_unconfined` is attached to a tooled codex or grok
  seat today, and its mode is `unconfined`.

## Design

**A seat uid for the owner route, on the compute host only.** When the far end runs a
codex or grok leg it gives the owner route the jail's identity:
- it leases a seat id for the life of the leg and holds the egress namespace in the
  unmapped form mapped onto the account's subordinate range;
- it hands the sandbox's tree and output files to that uid with `seat_uid.handoff`;
- the identity switch and the owner take **the leased uid and gid** where they take the
  operator's today. Capabilities are exactly the local route's: codex keeps
  `SEAT_RETAINABLE_CAPS`, grok keeps none. The private home is unchanged: memory-backed,
  inside the seat's own mount namespace.
- the launch probe additionally asserts that the seat's uid is the leased one and is not
  the account's.

The variant is selected by the far end's seat run and by nothing else. A local launch
takes today's path, argument for argument; that is checked against the goldens.

**The tree at a fixed path.** For a placed codex or grok seat the tree is bound at
`seat_jail.SEAT_TREE` instead of at the launching host's staged path, and the launching
host renders the sealed prompt with that fixed path when the leg is a placement candidate.
The prompt the provider receives is the prompt whose digest the launching host recorded.
If placement falls back to local, the prompt is rendered again for the local path before
the local launch, and that digest is the one recorded.

**Credentials** (ruling B1; default answer to Q2 of P1: only an expiring access token is
ever placed).

| | Placed codex seat | Placed grok seat |
|---|---|---|
| What the slot holds | The narrowed auth file: access token and id token, refresh token blanked; the one-line config | The narrowed auth file: the bearer, no refresh keys; the agent id |
| Does it expire | Yes when the login is a subscription login: both tokens carry their own expiry, which the launching host reads. **Not in API-key mode.** | **Not as far as the runtime can tell.** |
| Default | Placed only when the file holds no API key and both tokens have a readable expiry with the margin left. Otherwise not a candidate (`seat_placement_credential_not_placeable`); the seat runs locally. | **Not a candidate. The seat runs locally.** |
| With the switch on (Q2 ruled "yes") | API-key mode may be placed | May be placed |
| On the compute host | Bytes from the request, through P3's credential source, into the seat's private home | The same |
| Where it lives there | Memory only: files in a memory-backed home inside the seat's mount namespace | The same |
| Destroyed on clean exit, on a kill, on out-of-memory, on reboot | With the seat's namespace, in every case. By construction, given that swap is zero for the account and core dumps are off, both checked by host qualification (P2). | The same |

One thing is on disk for these seats: their **output files**, which the owner binds
writable so the answer survives the seat. The runtime redacts credential values from them
on a clean exit. If the entry point is killed first, an output a CLI wrote a credential
into stays on disk, owned by the seat's uid, until the next session's sweep (P2). That is
the stated limit for these seats; the kill-then-sweep case below covers it.

**Placed.** `PLACED_HARNESSES` gains `codex`, and `grok` when the switch is on. A placed
seat's mode is `remote`; `seat_filesystem_unconfined` describes the local route and is not
attached to a placed seat.

**Separation, proven through this view too.** Host qualification's separation probe (P4)
runs through **each** view a placed seat can take: the jail's, and now the owner route's
seat-uid variant, with a neighbour seat of another principal running. The list is P4's:
paths; pids and signals; abstract and pathname unix sockets; System V and POSIX IPC; the
account's keyring; inherited descriptors. `READY` names the views that passed, and the far
end admits a harness only if its view passed.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_seat_identity_switch`, the owner arguments in `launch_provider`, and `launch_owned` —
  modify — accept a seat identity (uid, gid) that defaults to the operator's. Only
  `execute_leg_request` passes one.
- `execute_leg_request` — modify — for a codex or grok leg: lease, mapped holder, handoff,
  seat identity, the tree at the fixed path.
- The launch probe — modify — the leased-uid assertion when a seat identity is given.
- The sealed-prompt call site — modify — the fixed tree path for a candidate; re-rendered
  on fallback.
- `_narrow_seat_credentials` (P3) — modify — reports, for codex and grok, whether what it
  narrowed is placeable under the default rule.
- `PLACED_HARNESSES`, `_placeable` — modify.

### `phase-loop-runtime/src/phase_loop_runtime/seat_uid.py` (modify)
- `handoff` — modify — only if its present form, written for the jail's directory layout,
  cannot hand over the owner route's tree and output files. The jail's use of it must not
  change.

### `phase-loop-runtime/src/phase_loop_runtime/placement_entry.py`, `placement_leg.py` (modify)
- The separation probe — modify — the second view; `READY` reports views per harness.
- The request's credential slot — modify — files for codex and grok.

### `phase-loop-runtime/tests/test_placed_owned_seat.py` (create); `tests/test_placed_seat.py`, `tests/data/seat_launch_references.json` (modify)
- The falsifiers under "Verification".

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify —
  SEATOWNER: on a compute host the owner route takes a leased seat uid, and what that does
  and does not change; the credential table; that a placed codex or grok seat is `remote`,
  not `unconfined`. The local route's text is unchanged.
- `docs/phase-loop/remote-seat-host.md` — modify — the codex and grok CLIs at the launching
  host's versions; that the workspace and the per-version runtime directory must not sit
  under a directory the seat's view binds whole.
- `docs/advisor-board-capabilities-card.md` — modify — which harnesses are placed, and
  under which credential rule.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none.

## Dependencies & order
1. Needs P4 merged.
2. **This unit changes what a seat sandbox is, on the compute host only:** the kernel uid a
   placed codex or grok seat runs as, and the path its tree is bound at. That is the ruling
   RD3 (ii). It changes no bind, capability, namespace or network rule of a local seat, and
   nothing about the jail: the seat-jail profile digests and the falsifier layout identity
   are recorded before and after and must be equal.
3. No agy route-core file is edited.
4. Order: the seat-identity parameter with the local goldens unchanged; the fixed tree path
   and prompt; the far end's lease and handoff; the probe's second view; the credential
   rule; then `PLACED_HARNESSES`, last.

## Verification

```sh
cd phase-loop-runtime
PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_placed_owned_seat.py tests/test_placed_seat.py tests/test_placement_entry.py \
  tests/test_sandbox_ssh.py tests/test_sandbox_placement.py \
  tests/test_seat_sandbox_permissions.py tests/test_seat_notices.py \
  tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py \
  tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py \
  tests/test_harden_evidence_verifier.py
ruff check .
```

Run on Python 3.12 and 3.10, with P4's fixtures: the far end on the same machine with its
own home and stores, stand-in CLIs, login fixtures in the CLIs' real file shapes. Tests
that need a subordinate range skip, with the existing reason, where the host has none. Each
case is control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| A local codex and grok launch | Plan 1a's golden and the launch-spec golden match; the argument list is identical to the base's | Pass a seat identity locally |
| A placed codex seat | Its processes run as a leased subordinate uid: not the account's, not another running seat's; capabilities are the local route's; zero local provider spawns; mode `remote` | Map to the account uid on the far end |
| Two placed seats of two principals at once | Different uids; neither can signal the other or the entry point even with the pid namespace removed from one | Lease one id for both |
| Separation probe through the owner route's seat-uid view, beside another principal's seat | Every item in P4's list fails for the probe | Drop the pid namespace; drop the IPC namespace; launch outside the filtered namespace; bind the workspace root |
| A harness whose view failed the probe | Not admitted on that host; the other harnesses are | Admit by host verdict alone |
| The stand-in CLI checks the directory its prompt names | It exists and is the tree, on the far end and, after a fallback, locally | Render the launching host's path for a placed leg |
| The prompt digest | The one recorded is of the prompt the provider received, placed and after fallback | Record before re-rendering |
| Codex login with tokens that expire and no API key | Placed; the far-end home holds byte-for-byte what a local seat's holds | Forward the unnarrowed file |
| Codex in API-key mode; a token with no readable expiry; a token short of the margin | Not a candidate, `seat_placement_credential_not_placeable`; runs locally. With the switch on, API-key mode is placed. | Place whatever narrowing returns |
| Grok | Not a candidate by default; placed with the switch on | Treat an unreadable lifetime as expiring |
| The encoded request | No refresh-token value; with the switch off, no API key and no bearer without an expiry | Decide placeability on the far end |
| During a placed seat; after a clean exit | No file under the entry point's directories holds a credential value; output files are redacted | Skip redaction for placed seats |
| Entry point killed with SIGKILL while a stand-in CLI has written a credential value to its output; then a session of a **different** principal | No process remains; the sweep removes the seat-uid-owned output and tree; until then the seat id is not leased | Sweep through the account uid |
| Verifier, placed codex record | The placed shape passes; the EC-HARDEN-5 predicate gives the same answer it gives a local tooled codex record | Force the residual for every placed record |
| Mode and notices | `remote`; no `seat_filesystem_unconfined` on a placed seat; unchanged locally | Carry the local notice |

**Live check, outside CI.** `phase-loop placement qualify <name> --seat codex` (and
`--seat grok` if the switch is ever turned on), then one board against a real compute host.
Recorded in the PR: each vendor's response; the uids the seats ran as; the scan of the real
output files for a credential value.

## Acceptance criteria
- [ ] A placed codex seat runs under a leased subordinate uid that is neither the account's
  nor another running seat's, with the local route's capabilities, and a local codex
  launch's argument list is identical to the base's.
- [ ] The separation probe, run through the owner route's seat-uid view beside another
  principal's seat, fails on every listed item and passes its mutations only when they are
  applied.
- [ ] Codex in API-key mode, and grok, are not placed by default and run locally with
  `seat_placement_credential_not_placeable`; no API key and no non-expiring bearer appears
  in any encoded request.
- [ ] An entry point killed while a placed seat's output holds a credential value leaves
  nothing that the next session of a different principal does not remove.
- [ ] The stand-in CLI finds the tree at the path its prompt names, and the recorded prompt
  digest is of the prompt it received.

## Maintainer decisions

**Rulings relied on:**

| Ruling | What it fixes in this plan |
|---|---|
| RD3, legs (ii), 2026-09-29: codex and grok under a subordinate uid on the remote | The whole unit |
| Accounts (B6), 2026-10-10: one shared account first | Why RD3 (ii) cannot be deferred: with one account it is the only kernel boundary between two users' codex or grok seats |
| Logins (B1), 2026-10-10: the launching user's, per run, in the access-only form | The credential table |

**Known risks, each with its check:**

| Risk | Check |
|---|---|
| Root on the compute host can read a login in memory while a seat runs | Bounded by expiry under the default rule; stated in the mode line and operator guide |
| A vendor may object to a login used from the compute host's address | `placement qualify --seat <harness>` records each vendor's response |
| A CLI may write a credential into its output, which is on disk | Redaction on clean exit; the kill-then-sweep case; the live scan |

**Open:** Q2 of P1. Until it is ruled, grok is not placed and codex is placed only on a
subscription login.

## Execution Policy

- execute: effort=max, reason=changes the kernel identity of a seat sandbox on the compute host and decides which vendor credentials may leave the launching host
