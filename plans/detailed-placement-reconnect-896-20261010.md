---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244]
builds_on: [plans/detailed-remote-seat-placement-896-20261010.md, plans/detailed-ssh-placement-backend-896-20261010.md]
automation:
  suite_command: "cd phase-loop-runtime && PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_reconnect.py tests/test_sandbox_ssh.py tests/test_placement_entry.py tests/test_placement_driver.py tests/test_placement_lease.py tests/test_seat_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_advisor_board_config.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: a placed workload survives a dropped connection and is resumed by the run that launched it (agent-harness#896, P2b)

## Task

The maintainer ruled on 2026-10-10 (question Q1): when the connection to the compute host
drops after a workload has started, the compute host **keeps it alive for a limited time
and lets the launching host resume it, tied to that run**. The time is a setting with a
default of about 30 minutes. The maintainer was told this costs more protocol and a later
first placed seat, and chose it.

P2 (`plans/detailed-ssh-placement-backend-896-20261010.md`) builds the transport with the
simple rule: the session is the lease, and a dropped session ends the workload. This unit
replaces that rule for a started workload. It lands after P2 and **before** the first placed
seat (P4), so no seat is ever placed under the simple rule. It is its own unit because P2
is already one full review and this is a distinct change: a process that outlives its SSH
session, and a resume protocol.

The driver flag stays off. This unit is proven with the null workload.

Cited, not restated: amendments C1–C12 of
`plans/detailed-remote-seat-placement-896-20261010.md` (P1). C12 is the seam's side of this
unit.

## Research summary

- **What ends a workload in P2.** The entry point is the forced command of the SSH session.
  It reads its input continuously and ends the workload at end of input.
- **What the server does on a drop**, established by experiment during review of the host
  procedure (OpenSSH 8.9): a forced command without a terminal sees end of input within
  seconds; the server sends it no hangup; processes it started survive unless they act on
  the end of input themselves.
- **Where such a process lives.** With the standard login stack a session's processes are
  in a per-session group under the account's own resource group, and stay there after the
  session ends unless the host is configured to kill a user's processes at logout (off by
  default on the distributions this runtime supports). So a process that outlives the
  session is still under the account's memory, CPU, task and device limits.
- **What the sweep keys on.** P2's start sweep removes a sandbox directory only when its
  lock is free. A lock is held by a live process, whatever session started it.
- **What the launching side holds.** P1's lease: an id allocated and fsynced before any
  remote effect, and a lock held by the owning process for the life of the leg.
- **The account has no service of its own.** The host procedure gives it no user service
  manager, no scheduled jobs and no lingering. Nothing in this unit needs one.

## Design

**Two processes on the compute host instead of one.**
- The **relay** is the forced command of a session. It authenticates nothing itself: the
  principal comes from the key line, as in P2. It relays frames between the session and a
  keeper.
- The **keeper** is started by the relay when `EXECUTE` arrives. It detaches fully from the
  session (its own session and process group, standard streams closed, hangup and
  broken-pipe signals ignored) and stays in the resource group it was born in. It owns the
  workload: it holds the sandbox's lock and its capacity slot, runs the workload, buffers
  what the workload produces, and listens on a socket inside the sandbox's own state
  directory, which only the account can reach.
- Everything before `EXECUTE` is unchanged from P2: a session that ends before a workload
  has started removes the sandbox at once.

**States of a started workload.**

| State | Meaning | Leaves it when |
|---|---|---|
| attached | Exactly one relay is connected | The session ends, or no frame arrives for the lease time: → detached. `RESULT` acknowledged, or `CANCEL`: → ended |
| detached | No relay. The workload keeps running; a finished result is held. | A valid `RESUME`: → attached. The reconnect window lapses: → ended |
| ended | The keeper has stopped the workload through its ordinary quiescence path, destroyed what it held in memory, removed the sandbox's files, released the slot and the lock, and written a tombstone | — |

**The reconnect window.** One number per workload, fixed at `EXECUTE`:
- the launching side's setting: `[sandbox] reconnect_window_s` in the user configuration,
  overridden by `PHASE_LOOP_SANDBOX_RECONNECT_WINDOW_S`; default 1800;
- never more than the compute host's own maximum, from its root-owned configuration
  (default 1800);
- and a kept workload never outlives what it is allowed to hold: the keeper also receives
  an absolute time, the earliest of the leg's deadline, where it has one, and the expiry of
  the credential placed with it, where one was placed. The window ends at that time if it
  comes first. If that time has already passed at the moment of the drop, the workload is
  ended at once.

A window of zero restores P2's rule for that workload.

**Resume is bound to the run.** A new session presents `RESUME` with the lease id, an
attach number and the last position it acknowledged.
- The relay finds the keeper **only** under the principal the key line names. Another
  user's lease id, an unknown lease id and a mistyped one all get the same answer,
  `sandbox_ssh_resume_not_found`: there is no oracle.
- The lease id is the one the launching side allocated before any remote effect (C6) and
  sent in `HELLO`. Only the process that holds that lease's lock on the launching host
  resumes; a restarted runtime does not hold it, does not resume, and its reaper kills the
  sandbox by lease id as for any dead owner. If it never gets there, the window ends it.
- **One controller.** While a relay is attached a second `RESUME` is refused
  (`sandbox_ssh_resume_controller_attached`) and the attached one is not disturbed.
- **No replay.** The keeper accepts an attach number only if it is greater than the last
  one it accepted; otherwise `sandbox_ssh_resume_replayed`.
- After the window, or after the workload ended for any reason, `RESUME` gets
  `sandbox_ssh_resume_expired`, answered from the tombstone. The launching side records
  the leg as `sandbox_placement_lost_after_launch`. The workload is never run again and
  never moves.

**Positions and acknowledgement.** Every frame the keeper produces after `STARTED` carries
a position, counting from one. The launching side sends `ACK` with the highest position it
has received in order: on an interval while attached, with every `RENEW`, and in `RESUME`.
The keeper retains every frame above the acknowledged position, within a configured bound,
and on resume sends them again in order; the launching side discards any position it
already has. While detached the keeper does not accumulate liveness frames: it keeps only
the latest progress number, and the result, which is always retained and is already
bounded by P2's maximum. So the buffer cannot grow without limit, and nothing is lost that
the launching side needs.

**Cancel while detached.** The launching side cannot deliver it. It sends `CANCEL` as the
first frame after a successful `RESUME`; if it cannot resume, the window ends the workload.
Whichever comes first. The driver's cancel returns within its bound either way (C4), and
the lease entry stays for the reaper when the kill was not confirmed.

**What the launching side does while detached.** The backend's `wait` returns the seam's
`ExecDetached` (C12) and keeps trying to resume, with backoff, each attempt preceded by its
own connection attempt as in P2. The driver's rules for that state are in C12: the time is
charged to a bounded leg's deadline; under heartbeat-only it is recorded as
`placement_detached` and the stall clock does not run; the notices `seat_placement_detached`
and `seat_placement_resumed` are shown.

**The properties the simple rule gave are kept.**
- Nothing runs with nobody able to reclaim it for longer than the window: the keeper ends
  the workload itself, with no session and no service needed.
- If the keeper is killed, the workload dies with it (the far end's namespaces are tied to
  their owner), its lock is free, and the next session's sweep removes the files and
  writes the tombstone, exactly as P2's sweep does for a dead entry point.
- The sweep never touches a detached workload inside its window: its keeper is alive and
  holds the lock.
- The slot stays held while detached, so the cap still means what it says.
- The keeper drops the credential slot of the request from its memory as soon as the
  workload has started; while detached it holds no credential of its own.

**Tombstones.** One small record per ended workload under the principal's state directory:
lease id, reason, time. No request or result bytes. Kept for a bounded time and count.

**Host prerequisites this adds, checked by host qualification and printed.**
- The host must not kill a user's processes when their session ends. Qualification reads
  the login manager's setting; where it is on, the compute host reports that it cannot
  keep a workload, every window is zero there, and the launching side shows
  `seat_placement_reconnect_unavailable`.
- Whether the host removes a user's inter-process objects at logout is reported. The
  keeper and the workloads of this slice own none under the account's uid, so it is not a
  failure.
- `phase-loop placement qualify` proves the first on the real host by doing it: it drops
  its own connection mid-workload and resumes; and, with a window of a few seconds, drops
  it and checks after the window that nothing is left.

**Protocol.** `placement_ssh.v2` replaces `v1`: the fixed command string carries the
version, and a mismatch is `sandbox_ssh_protocol_mismatch`. Additions: positions on
far-end frames; `ACK`; `RESUME` and its four refusals; `DETACH_INFO` in `STARTED` (the
window and the absolute bound the keeper will apply). Codes, registered with their classes
(C7): the four `sandbox_ssh_resume_*` codes are post-launch and belong to no admission
class; `seat_placement_reconnect_unavailable`, `seat_placement_detached` and
`seat_placement_resumed` are notices.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/placement_entry.py` (modify)
- The relay and keeper split, the state table, the window, tombstones — add.
- `RESUME` handling in the relay — add.
- The sweep — modify — writes a tombstone when it removes a sandbox that had started a
  workload.
- Host qualification — modify — the two prerequisites above.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_ssh.py` (modify)
- The frame codec — modify — `placement_ssh.v2`.
- `SshBackend.wait` — modify — returns `ExecDetached` on a lost session after `execute`,
  resumes, de-duplicates by position, sends `ACK`.
- `SshBackend.cancel`, `release` — modify — the detached cases.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `sandbox_policy.py` (modify)
- `_KNOWN_SANDBOX_KEYS` — modify — add `reconnect_window_s`; `reconnect_window_s()` — add —
  the configuration value with its environment override, default 1800.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `placement qualify` — modify — the drop-and-resume and drop-and-expire checks.

### `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `panel_invoker.py` (modify)
- `NOTICES` and `_HARNESS_DETAIL_CODES` — modify — the codes named under "Protocol", added
  the way each closed list already grows.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … a HARNESS CODE — a fixed string this
  runtime itself emits (`_HARNESS_DETAIL_CODES`)". Members are added by that mechanism; no
  template or category is added.

### `phase-loop-runtime/tests/test_placement_reconnect.py` (create); `tests/test_sandbox_ssh.py`, `tests/test_placement_entry.py`, `tests/test_advisor_board_config.py`, `tests/data/seat_launch_references.json`, `tests/test_agent_cli_scratch_inventory_1147.py` (modify)
- The falsifiers under "Verification".
- P2's "client killed mid-workload: workload gone within the lease time" case changes: with
  a non-zero window the workload is kept. It is replaced by the window-zero case and the
  expiry case below, and listed in the PR body.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — the SSH
  backend subsection: the keeper, the state table, the window rule, the binding, positions
  and acknowledgement, the tombstone.
- `docs/phase-loop/remote-seat-host.md` — modify — the two host prerequisites; that no
  lingering, service or scheduled job is needed; the maximum window in the configuration
  file.
- `docs/phase-loop/convergence-runtime.md` — modify — the window setting.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none.

## Dependencies & order
1. Needs P1 (with C12) and P2 merged. P4 needs this unit.
2. No agy route-core file is edited. Nothing a seat sandbox permits changes.
3. Order: the codec; the keeper over a pipe with a fake relay; the relay; the backend's
   detach and resume against the loopback fixture; `qualify`.

## Verification

```sh
cd phase-loop-runtime
PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_placement_reconnect.py tests/test_sandbox_ssh.py tests/test_placement_entry.py \
  tests/test_placement_driver.py tests/test_placement_lease.py tests/test_seat_notices.py \
  tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py \
  tests/test_advisor_board_config.py
ruff check .
```

Run on Python 3.12 and 3.10, with P2's fixtures. The null workload is given a mode that
emits numbered progress and then a result, so order and completeness can be checked. Each
case is control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Drop the connection mid-workload (kill the `ssh` client); resume inside the window | The workload never stopped; the launching side receives every position once, in order, and the result | Start numbering again at resume; resend from the first frame without de-duplication |
| The workload finishes while detached; resume | The held result arrives; then the sandbox is removed | Discard a result with no relay attached |
| `RESUME` under another principal with the right lease id; with an unknown lease id | Both `sandbox_ssh_resume_not_found`, byte-identical answers; the workload is undisturbed | Look the lease up across principals |
| `RESUME` with a stale lease id of an ended workload | `sandbox_ssh_resume_expired`; the launching side records `sandbox_placement_lost_after_launch` | Start a new workload for it |
| A second `RESUME` while a relay is attached | `sandbox_ssh_resume_controller_attached`; the first controller keeps receiving in order | Replace the attached controller |
| `RESUME` with an attach number already used | `sandbox_ssh_resume_replayed` | Accept any attach number |
| No resume; the window lapses | The workload is stopped through its quiescence path; no process, no sandbox directory, the slot free, a tombstone with the reason | Leave the workload running after the window |
| The window against its bounds: the host's maximum is smaller; the leg's deadline comes first; the placed credential's expiry comes first; that time already passed at the drop | The keeper ends the workload at the earliest of them; at once in the last case | Apply the setting alone |
| Window zero; a host that kills a user's processes at logout | P2's behaviour: ended on the drop; `seat_placement_reconnect_unavailable` in the second | Keep anyway |
| Cancel on the launching side while detached, then resume; and with no resume possible | `CANCEL` is the first frame after `RESUME`, then `KILLED`; the window ends the workload, and the driver's cancel returned within its bound | Drop the pending cancel at resume |
| Keeper killed with SIGKILL while detached; then a session of a different principal | The workload is dead; the sweep removes the directory and writes a tombstone; a later `RESUME` gets `sandbox_ssh_resume_expired` | Sweep only directories with no lease marker |
| A detached workload inside its window, while fifteen other sessions start | No sweep touches it; its slot stays counted | Decide liveness by session |
| The launching process is killed while detached; a new runtime starts | It does not resume; its reaper kills the sandbox by lease id, or the window ends it; never two controllers | Resume from the journal alone |
| Session open but silent for longer than the lease time | Treated as a drop: the far end closes it and the window starts | End the workload |
| Frames buffered while detached for longer than the buffer bound allows | Only the latest progress number and the result are held; memory stays within the bound | Buffer every liveness frame |
| The keeper after the workload has started | Its memory holds no credential slot (a marker value given as the slot is absent from a dump of its request object) | Keep the whole request for the workload's life |
| The keeper's resource group | The account's own, with its limits, after the session that started it has ended | Start the keeper through a path outside the session |
| Through the driver: a bounded leg detached for part of its deadline; a heartbeat-only leg detached | The deadline kept running and expires on time; `placement_detached` is recorded, no stall notice while detached, `seat_placement_detached` then `seat_placement_resumed` | Pause the deadline while detached |
| `placement qualify` on the fixture | Drop-and-resume completes; drop-and-expire with a short window leaves nothing | Skip the resume check when the first passes |

## Acceptance criteria
- [ ] A connection dropped mid-workload and resumed inside the window delivers every
  position exactly once, in order, and the result, through the real `ssh` client on the
  loopback fixture.
- [ ] A `RESUME` under another principal, with an unknown or stale lease id, with a used
  attach number, or while a controller is attached is refused with its typed code, and in
  the first two cases the answers are identical.
- [ ] When the window lapses, and when the earlier of the leg's deadline and the
  credential's expiry is reached, the keeper ends the workload: no process, no directory,
  the slot released, a tombstone written; a later `RESUME` yields
  `sandbox_placement_lost_after_launch` and nothing is run again.
- [ ] A keeper killed while detached leaves nothing that the next session of a different
  principal does not remove, and a detached workload inside its window is never swept.
- [ ] The keeper runs under the account's resource limits after its session has ended, and
  holds no credential once the workload has started.

## Maintainer decisions

**Ruling of 2026-10-10 (Q1), relayed by the team lead:** keep the seat for a reconnect: the
compute host keeps it alive for a limited time and lets the launching host resume it, tied
to that run; "parameterize the wait time so it can be set in settings with a smart
default. Maybe 30 minutes or so."

| Part of the ruling | Where |
|---|---|
| Kept for a limited time, resumable | The keeper and the state table |
| Tied to that run | The lease id, the principal, one controller, no replay |
| A setting with a smart default | The window rule: 1800 seconds, never more than the host's maximum, never past the leg's deadline or the credential's expiry |

**Open:** none.

## Execution Policy

- execute: effort=max, reason=a process that outlives its session on a shared account, and a resume protocol whose binding decides who may take over a running seat
