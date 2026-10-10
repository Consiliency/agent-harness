---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1246, agent-harness#1162]
builds_on: plans/detailed-remote-seat-placement-896-20261010.md
automation:
  suite_command: "cd phase-loop-runtime && PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_sandbox_ssh.py tests/test_placement_entry.py tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_seat_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_gate_a_wheel_isolation.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: an `ssh` placement backend, its compute-host entry point and `phase-loop placement qualify`, proven with a null workload (agent-harness#896, P2)

## Task

This unit is the transport and the far end of the first slice: an `ssh`
`ExecutingBackend` behind the placement seam, the entry point it talks to on the compute
host, and the command that qualifies a compute host. It stages a tree there, verifies it,
runs a **null workload**, and cleans up. It runs no vendor CLI and carries no credential.

The driver flag stays off. `_default_spawn` never calls this backend in this unit, so a
user who configures an `ssh` root in order to qualify it loses nothing: their seats run
locally exactly as today, with the existing `sandbox_placement_driver_unavailable` record.
Qualification is the `qualification` workload of amendment C10.

The seam, amendments C1–C11 and the driver are in
`plans/detailed-remote-seat-placement-896-20261010.md` (P1). This plan cites them and
restates none.

**General product.** Nothing here names a host, an account, an address or a tailnet. The
destination is configuration. CI needs no particular host: every test runs against a
throwaway `sshd` on loopback, or against the entry point over a pipe.

## Research summary

- **The seam.** A backend registers under a URL scheme through the entry-point group
  `phase_loop_runtime.placement_backends`, loaded only when a configured root names that
  scheme. `pyproject.toml` already declares entry points of this kind for other groups.
- **Roots.** `sandbox_policy.parse_location` keeps a URL root's scheme, host, port and path,
  drops userinfo at parse, and lower-cases the host. An `ssh` root cannot carry an account
  name; the account comes from the operator's SSH client configuration.
- **SSH facts established by experiment during review of this plan** (OpenSSH 8.9):
  - `ssh` exits 255 for an unreachable host, a refused key and a changed host key alike;
  - a forced command receives the client's requested command verbatim in
    `SSH_ORIGINAL_COMMAND`, the server's and client's addresses in `SSH_CONNECTION`, and
    sees end of input within seconds when the client exits or is killed;
  - a server-side `ForceCommand` replaces a per-key `command=`, argument included;
  - a `nologin` shell means the forced command never runs; a forced command runs through
    the account's login shell;
  - `ssh -W <host>:<port>` asks for a forwarding channel at once and exits 255 when it is
    refused; `ssh -N -L` stays silent either way;
  - an unprivileged `sshd` refuses an `authorized_keys` file under a world-writable parent
    unless `StrictModes no`.
- **Identity.** The installed `RECORD` of one wheel differs between two installs (console
  scripts embed the prefix; installers write different rows). A runtime run from a source
  tree has no `RECORD`. It cannot be the identity two hosts compare.
- **The stage digest.** `review_stage.review_tree_manifest_sha256` skips everything under
  `.git`, and the stage is a clone whose `.git` the seat uses.
- **Local pieces the far end reuses unchanged:** `sandbox_egress.isolated_network` and
  `host_addresses` (a seat's namespace rejects every address of the host it runs on before
  anything else); `seat_uid.subordinate_range` (it uses the account's first usable range);
  `seat_uid.mapped_namespace`; `seat_jail_prerequisites.check`.
- **CI.** The CI image and the workflow's package lists install no SSH server
  (`ci/dagger/src/agent_harness_ci/main.py`, `.github/workflows/test.yml`).

## Design

**Root.** `ssh://<destination>[:<port>]` with an empty path. `<destination>` is a host
name or a lower-case alias in the operator's SSH client configuration. The backend resolves
it with `ssh -G` and refuses, as `sandbox_ssh_root_invalid`, a root with a path, an alias
that does not resolve, or a destination reached through a proxy command or a jump host: the
backend must be able to open its own connection to the resolved address.

**Who decides "unreachable".** Before it starts `ssh`, the backend opens a TCP connection
to the resolved address and port itself, within the operation bound. Only a failure of
**that** attempt is `unreachable`. If the address accepts a connection and `ssh` then
fails before the first frame, the host is up: the outcome is `identity_mismatch` when
`ssh` reports a host-key failure, `not_enrolled` when it reports that authentication was
refused, and `refused` otherwise. The reading of `ssh`'s diagnostics, under a fixed locale,
only chooses among classes that never run locally; it can never produce `unreachable`.

**One session per sandbox; the session is the lease (built behaviour, pending Q1 of P1).**
`admit` starts the client and holds the session until `release`. The far end kills the
sandbox and removes its directory when the session ends for any reason: end of input, a
cancel, or no frame within its lease time. The entry point reads its input continuously
while a workload runs, so it sees the end of the session at once. The cost: a dropped
connection, or a launching host that stalls for longer than the lease time, ends a launched
seat with no fallback.

**The client forces what it can.** Fixed on every invocation: no terminal, batch mode, no
agent, X11 or port forwarding, no connection sharing, no local command, no environment
sent, strict host-key checking, a bounded connect time, keep-alives, IPv4 or IPv6 as
resolved. The remote command is the fixed string
`phase-loop-seat-entry placement_ssh.v1 <runtime version>`. The child's environment is a
fixed short list. Its stderr goes to the private leg log and never into a detail.

**Wire protocol `placement_ssh.v1`.** Length-prefixed frames. Control frames are JSON with a
closed key set. The far end is a strict state machine: a frame that is not valid in the
current state ends the session and removes the sandbox.

| State | Frames accepted | Then |
|---|---|---|
| start | `HELLO` (protocol, runtime version, runtime digest, workload, owner id, lease id, declared stage bytes, nonce) | `READY` (report) or `REFUSED` (code) |
| ready | `STAGE` chunks, `STAGE_END` (tree digest, archive digest) | `COMMITTED` (sandbox ref, both digests as recomputed there) or `REFUSED` |
| committed | exactly one `EXECUTE` (workload, request bytes) | `STARTED` |
| running | `RENEW`, `CANCEL` | `PROGRESS` (seq), `PING`, then `RESULT` (exit status, result bytes, truncated, echo of the request digest) |
| any | `CANCEL` | `KILLED`, then the session closes |
| control session | `LIST` (owner id) → pairs of sandbox ref and lease id; `KILL` (sandbox ref, lease id) → `KILLED` | closes |

Every frame read has a finite timeout on both sides, independent of a seat's thinking
time: while a workload runs the far end sends `PING` on an interval, and the client treats
silence for longer than the lease time as a lost session. Stage bytes are counted as they
arrive against the declared size, the configured maximum and the free-space floor; the
count going over ends the session.

**Runtime identity.** The digest in `HELLO` is computed from the package's own files as
installed: the sorted list of relative path and sha256 for every file under
`phase_loop_runtime/`, bytecode caches excluded. It does not depend on the installer, the
prefix or the console scripts. A source checkout computes the same thing over its
`src/phase_loop_runtime` tree, so it matches only an identical tree. The entry point
refuses a digest that differs from its own.

**Admission codes and their classes** (registered with the driver per C7; each a `NOTICES`
row with a fix line):

| Code | Class |
|---|---|
| `sandbox_ssh_unreachable` | `unreachable` |
| `sandbox_ssh_not_enrolled` | `not_enrolled` |
| `sandbox_ssh_host_key_mismatch` | `identity_mismatch` |
| `sandbox_ssh_capacity`, `sandbox_ssh_host_qualifying` | `at_capacity` |
| `sandbox_ssh_root_invalid`, `sandbox_ssh_client_missing`, `sandbox_ssh_session_refused`, `sandbox_ssh_protocol_mismatch`, `sandbox_ssh_runtime_unavailable`, `sandbox_ssh_host_unqualified`, `sandbox_ssh_below_floor`, `sandbox_ssh_stage_too_large`, `sandbox_ssh_snapshot_mismatch`, `sandbox_ssh_archive_mismatch` | `refused` |

**The far end.**
- **A root-owned shim** (`deploy/phase-loop-seat-entry.sh`, POSIX `sh`, shipped as package
  data) is the forced command of each key. It treats `SSH_ORIGINAL_COMMAND` as data: it
  accepts exactly the fixed command string, never passes it to a shell, and maps the
  version to an installed runtime directory. It starts the entry point with an empty
  environment, an absolute `PATH`, the interpreter's isolated mode, and the principal name
  the server configuration bound to that key. Any other request, a version that is not
  installed, or an invocation as a login shell exits with a fixed status and runs nothing.
- **What the entry point trusts.** Only the principal name from the key line, checked
  against `[a-z0-9][a-z0-9_-]{0,31}`. Its input is hostile: every size is bounded, and
  archive members are checked (below). It reads configuration only from the one root-owned
  file, refuses to run if that file is missing, not root-owned or writable by anyone else,
  and refuses if its own home directory or the runtime it runs from is writable by its
  uid. It never lets a child inherit the session's input or output. Before any other
  runtime code runs it sets its runtime directory to the state directory the configuration
  names, so every seat-id lease on the host uses one lock directory; main's fallback to a
  per-uid directory under the temporary directory is never taken.
- **Configuration** (a closed key set): the workspace and state directories; whether the
  workspace must be a mount point of its own (default yes, so everything written sits
  under one bounded file system); caps on concurrent sandboxes overall and per principal;
  the free-space floor; maxima for the stage, a frame, a request and a result; the lease
  time; the bound on host qualification; the arrival rule; the list of local sockets the
  account is allowed to reach (default none). It refuses a workspace that lies under a
  directory a seat's view binds whole, and a second, small cap bounds control sessions.
- **Arrival rule.** The entry point refuses a session whose server-side address is
  globally routable, and refuses when the port it arrived on is also listening on a
  globally routable address of the host. It reports both addresses of the session. A
  private source is admitted; pinning the source to one device is the server's job, by the
  key line.
- **Runs.** Every sandbox gets a fresh directory with an unpredictable name under the
  principal's directory (0700). It is never reused and is removed by the run that made it.
  Temporary files of account-uid processes go under the workspace. Retention and eviction
  never cross principals.
- **Stage.** Extraction refuses absolute names, parent references, hard links, devices and
  anything that would land outside the sandbox directory, and never follows a link. The
  archive carries the whole stage including `.git`. Two digests are checked: the archive's
  own sha256, which binds every byte including `.git`, and the tree manifest digest
  recomputed with `review_tree_manifest_sha256`. Either mismatch refuses and removes the
  partial state.
- **Isolation between principals.** `LIST` and `KILL` see only the caller's principal and
  owner id; any other reference is "not found".
- **Sweep.** At every session start, for **every** principal, the entry point removes
  sandbox directories whose lock is free. It removes through `seat_uid.mapped_namespace`,
  so directories that a later unit hands to a subordinate uid are removable; the sweep is
  bound to the entry point's own directory layout, not to retention records. A directory it
  cannot remove fails host qualification.
- **Core dumps and swap.** The entry point sets its core-size limit to zero and clears its
  dumpable flag before it reads a frame; its children inherit the limit.
- **`workload="qualification"`** runs the host probe and returns its report.
  **`workload="leg"`** is refused in `admit` (`sandbox_placement_workload_unsupported`)
  until P4.

**Host qualification.** The entry point keeps a verdict for its runtime digest, the current
boot, and the set of addresses and listening ports it saw. With no matching verdict it
runs the full probe before `READY`, under a host-wide lock and a time bound; a session that
arrives meanwhile is told `sandbox_ssh_host_qualifying`. The verdict file is an
optimisation, not an authority: the cheap checks marked ★ run at **every** admission.

Checked **as the account, outside any sandbox**, and again **under one of its subordinate
ids**:
- a TCP connection to each listening port on each address the host owns (loopback, private,
  tailnet-range, public, IPv6) fails. The listening table is the control: a port that is
  not listening is not counted as blocked. ★ one loopback listener;
- no pathname or abstract unix socket outside the configured allow-list accepts a
  connection (a local daemon's control socket is a side door no packet filter covers);
- name resolution and one public connection succeed, and the resolver address the host
  used is reported;
- ★ the process is in the account's own resource group, which has memory, swap, CPU and
  task limits, with the swap limit zero. A session started another way (an administrator's
  `sudo -u`) is reported as "not under the account's limits", not as limited;
- no device other than the standard pseudo-devices, pseudo-terminals and the tunnel device
  can be opened, and the tunnel device can;
- the account has exactly one subordinate uid range and one gid range, read from the same
  files the runtime reads.

Checked **from inside a network namespace built exactly as a seat's is, with an empty
private allowlist**: a TCP connection to every listening port on every address of the host
fails, and removing the host-address rule makes one succeed. The probes are TCP; UDP
services are not probed, and the report says so.

Also reported: `seat_jail_prerequisites.check`; the login shell; whether the home is
writable; whether any client environment arrived; the user-namespace restriction of newer
distributions. A failed check refuses every admission with `sandbox_ssh_host_unqualified`
until it passes.

**`phase-loop placement qualify <name>`**, from the launching host, drives a
`qualification` workload over a small synthetic tree through P1's driver, then:
- opens a second session, kills its own client mid-workload, and checks through `LIST` that
  nothing is left;
- asks the server for a forwarding channel to its own loopback (`ssh -W`) and for the
  file-transfer subsystem, and fails if either is granted.

It prints the report and exits non-zero if any property fails. What it proves: transport,
protocol, identity equality, cleanup, and the far end's own report. What it does not prove:
every capability in the report is the far end's claim (`backend_attested`), and one key is
one principal, so separation between two users on the real host is proven by the two-user
tests of P4 and P5, not by this command.

**Capabilities and declaration.** The backend declares `inbound_closed`,
`one_shot_secret_channel`, `private_ranges_unreachable`, `public_egress`,
`filesystem_confined` and `resource_bounded`, each recorded as `backend_attested` from
`READY`. Its declaration names the egress residual `resolver_allowed` (a seat resolves
names through the compute host's resolver) and no maximum lifetime.

**What SSH does about the maintainer's 2026-10-04 requirements on agent-harness#896.** Those
were written for the HTTPS service and stay attached to it. For this backend, as ruled on
2026-10-10:

| Requirement | This backend |
|---|---|
| Reachable only over the tailnet; qualification refuses a public listener | **Met differently:** the arrival rule (the far end refuses a public arrival address and a port also bound publicly). Restricting the source to one tailnet device is deployment. |
| A per-principal credential **and** a verified allowed source | **Met differently, by deployment:** one SSH key per user, pinned by the server to the launching host's address. No reusable secret crosses the wire. Only an OpenSSH server with a forced command is supported; a tailnet's own SSH server is not an equivalent and is not offered. |
| One principal per account on a shared launching host; easy issue and revoke | **Met:** the principal is the name the server binds to each key |
| Per-principal isolation by separate uid ranges | **Replaced for the first slice, by ruling:** one account. Every placed seat runs under its own leased subordinate uid (P4, P5); the entry point separates principals' directories. Per-user accounts are a named follow-on. |
| Per-principal caps: concurrent sandboxes | **Met** |
| Per-principal caps: total CPU and memory | **Not in the first slice, by ruling.** One limit bounds the whole account, so one seat can get another user's seat killed. A named follow-on. |
| Later: signed requests | **Already met** by SSH keys |

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_ssh.py` (create)
- `SshBackend` — add — the `ExecutingBackend` above. It resolves `ssh` with
  `review_stage.trusted_host_executable` and starts it under the infrastructure-launch
  marker.
- `register()` — add — registers the backend under the scheme `ssh` with the code table.
- The frame codec and `runtime_digest()` — add — shared with `placement_entry`.

### `phase-loop-runtime/src/phase_loop_runtime/placement_entry.py` (create)
- `main()` — add — the entry point above.
- The host probe — add.

### `phase-loop-runtime/src/phase_loop_runtime/deploy/phase-loop-seat-entry.sh` (create)
- The shim — add.

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project.entry-points."phase_loop_runtime.placement_backends"]` — add — `ssh`.
- `[project.scripts]` — add — `phase-loop-seat-entry`.
- `[tool.setuptools.package-data]` — modify — `deploy/*.sh`.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `placement` command, action `qualify <name>` — add.

### `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `panel_invoker.py` (modify)
- `NOTICES` and `_HARNESS_DETAIL_CODES` — modify — the codes in the table above, added the
  way each closed list already grows.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … a HARNESS CODE — a fixed string this
  runtime itself emits (`_HARNESS_DETAIL_CODES`)". Members are added by that mechanism; no
  template or category is added.

### `ci/dagger/src/agent_harness_ci/main.py`, `.github/workflows/test.yml` (modify)
- The package lists — modify — add the OpenSSH server and client, so the loopback fixture
  runs in CI. CI sets `PHASE_LOOP_REQUIRE_SSHD=1`, under which a missing `sshd` fails the
  test instead of skipping it.

### `phase-loop-runtime/tests/test_sandbox_ssh.py`, `tests/test_placement_entry.py` (create); `tests/data/seat_launch_references.json`, `tests/test_agent_cli_scratch_inventory_1147.py`, `tests/test_seat_notices.py` (modify)
- The falsifiers under "Verification"; the inventory rows for `sandbox_ssh` and
  `placement_entry`.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — an "SSH
  placement backend" subsection: the root form, who decides "unreachable", the session as
  lease, the protocol table, the codes and classes, the entry point's refusals, host
  qualification.
- `docs/phase-loop/remote-seat-host.md` — create — operator guide for a compute host: a
  plain POSIX login shell; a root-owned home with only named state directories writable;
  an SSH server instance for this account only, with a forced command per key and no
  server-wide forced command, no forwarding, no terminal, no client environment and no
  subsystem, and which exposes the session's addresses to the forced command; one source-pinned key per user; the configuration file; the workspace on a
  file system of its own; resource limits including a zero swap limit; an output filter
  for the account's ids built from the account database; closing local daemon sockets;
  denying scheduled jobs for the account; installing the runtime per version;
  `phase-loop placement qualify`. Example names and addresses use documentation ranges.
- `docs/phase-loop/convergence-runtime.md` — modify — the `ssh` root form.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none.

## Dependencies & order
1. Needs P1 merged.
2. No agy route-core file is edited.
3. Order: the frame codec and `runtime_digest`; the entry point over a pipe; the host
   probe; the backend against the loopback fixture; `qualify`; packaging; CI packages.
4. The compute host's account, limits, firewall and network grant are deployment work
   outside this repository. Nothing here waits on them or performs them.

## Verification

```sh
cd phase-loop-runtime
PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_sandbox_ssh.py tests/test_placement_entry.py tests/test_placement_driver.py \
  tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_seat_notices.py \
  tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py \
  tests/test_gate_a_wheel_isolation.py
ruff check .
```

Run on Python 3.12 and 3.10. Two fixtures: the entry point driven over a pipe, and a
throwaway unprivileged `sshd` on loopback with its own host key, a forced command per key,
and `StrictModes no` (its files live under the test's temporary directory). Without
`PHASE_LOOP_REQUIRE_SSHD` a missing `sshd` skips with a stated reason; with it, it fails.
At least one test in each group goes through the real `ssh` client. Each case is
control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Qualification through the driver | Admit, commit, execute, wait, release in order; zero local provider spawns; both digests recomputed by the far end equal the runtime's | Skip either recompute |
| One byte altered in a tracked file; one byte altered under `.git` | `sandbox_ssh_snapshot_mismatch`; `sandbox_ssh_archive_mismatch`; no directory remains | Check the tree digest only |
| Archive with an absolute name, a parent reference, a hard link, a device, a link pointing outside | Refused; nothing written outside the sandbox directory | Use the archive library's default extraction |
| More stage bytes than declared; than the maximum; than the floor allows | The session ends when the count crosses; no directory remains | Check the size once, at `HELLO` |
| `EXECUTE` before `COMMITTED`; a second `EXECUTE`; `STAGE` after `COMMITTED` | The session ends; the sandbox is removed; a second workload never starts | Accept frames in any state |
| Two installs of one build at different prefixes; one file changed in one of them; a source tree | Digests equal; `sandbox_ssh_runtime_unavailable`; equal only to an identical tree | Hash the installed `RECORD` |
| Port closed | `sandbox_ssh_unreachable`, class `unreachable` | — |
| Port open, key not in the fixture's key file | `sandbox_ssh_not_enrolled`; never `unreachable` | Map every `ssh` exit 255 to unreachable |
| Port open, host key changed | `sandbox_ssh_host_key_mismatch`; never `unreachable` | The same |
| Port open, forced command exits before a frame; `ssh` prints nothing recognised | `sandbox_ssh_session_refused`; never `unreachable` | Default to unreachable |
| Connection healthy, entry point stops answering (after `HELLO`, during `STAGE`, after `CANCEL`) | Each call ends within its bound as `sandbox_placement_operation_timeout`; a cancel returns within the bound | Read a frame without a timeout |
| Client killed with SIGKILL mid-workload | Workload gone and directory removed within the lease time; `LIST` empty | End the workload only on `CANCEL` |
| Entry point killed mid-workload; then a session of a **different** principal | The stale directory is removed at that session's start | Sweep the caller's principal only |
| A stale directory owned by a subordinate uid | Removed by the sweep; with removal through the account uid only, the sweep fails and the host is unqualified | Remove with a plain recursive delete |
| No frame for longer than the lease time; far end silent for longer than the lease time | Far end kills and removes; client reports the session lost | Renew on a timer at the far end |
| At the overall cap; at the per-principal cap | `sandbox_ssh_capacity`, class `at_capacity`; another principal below its cap is admitted | Count across principals for the per-principal cap |
| `LIST` and `KILL` for another principal's sandbox; `KILL` with the wrong lease id | "Not found"; the sandbox survives | Drop the principal filter |
| The shim: another command string; shell metacharacters; a version with a path separator; a login-shell invocation | Fixed non-zero exit; the entry point is not started; nothing is passed to a shell | Evaluate the string |
| The entry point: inherited environment variables; a writable home; a writable runtime directory; configuration missing, not root-owned (through an owner-check seam) or group-writable | Environment ignored; refuses before reading a frame | Read configuration from the home |
| Session arriving on a globally routable address; port also bound on one | Refused | Trust the client's claim |
| The entry point started with no runtime directory in its environment; two sessions at once | Both take seat-id locks under the configured state directory and get different ids; nothing is created under the temporary directory | Let `seat_uid.seat_runtime_dir` fall back |
| Host probe, account level: a loopback listener the account can reach | Verdict fails; every admission is `sandbox_ssh_host_unqualified` | Probe from inside a namespace only |
| Host probe, seat namespace: a listener on a host address | **Blocked: the verdict passes.** With the host-address rule removed from the namespace, the connection succeeds and the verdict fails | Count a listener's existence as a failure |
| Host probe: a connectable unix socket outside the allow-list; no limits; a non-zero swap limit; two subordinate ranges; an openable device outside the allowed set | Verdict fails in each | Report without measuring |
| A listener that appears after the verdict was cached; a loopback listener reachable at a later admission | The probe runs again; that admission is refused | Trust the cached verdict |
| Fifteen sessions arriving while the first probe runs | One probe; the others get `sandbox_ssh_host_qualifying` and retry | Run a probe per session |
| Forced client options | The recorded argument list carries every option under Design, with the operator's own configuration asking for forwarding, connection sharing and environment | Drop one option |
| Root with a path, with userinfo, with a proxy jump | Refused, or the userinfo absent from the argument list | Pass the configured text |
| `placement qualify` against the fixture; against a fixture whose server grants forwarding | Exit 0 with a complete report; non-zero | Use `ssh -N -L` for the forwarding check |
| `workload="leg"` | Refused in `admit`; no stage is sent | Refuse at `EXECUTE` |
| The driver flag | Still false; with an `ssh` root configured a board's seats run locally with the existing driver-unavailable record | Call the backend from `_default_spawn` |

## Acceptance criteria
- [ ] `phase-loop placement qualify <name>` against the loopback fixture, through the real
  `ssh` client, exits 0 with zero local provider spawns and both digests recomputed by the
  far end; a byte altered under `.git` yields `sandbox_ssh_archive_mismatch`.
- [ ] A reachable port with an unenrolled key, and with a changed host key, yield
  `sandbox_ssh_not_enrolled` and `sandbox_ssh_host_key_mismatch`; only a closed port
  yields the `unreachable` class.
- [ ] An entry point killed mid-workload leaves a directory that the next session of a
  different principal removes, including when that directory is owned by a subordinate
  uid.
- [ ] A listener on a host address that a seat namespace cannot reach passes host
  qualification; the same listener with the host-address rule removed, or a loopback
  listener the account itself can reach, fails it and every admission is refused.
- [ ] With an `ssh` root configured and this unit merged, a board's seats still run locally
  and `_NONLOCAL_EXECUTION_DRIVER` is false.

## Maintainer decisions

**Rulings of 2026-10-10** (relayed by the team lead):

| Ruling | What it fixes in this plan |
|---|---|
| Access (B5): a dedicated SSH port that admits only the seat account, key only, forced command, forwarding and terminals off, one source-pinned key per launching-host user in a root-owned file | The shim is a per-key forced command. Deployment, described in the operator guide. |
| Accounts (B6): one shared account first | Every principal shares one uid at the entry point; the entry point's trust rules, the all-principal sweep and the account-level probes exist because of it |
| Default (B2): opt in per user until `placement qualify` passes and a few boards run clean | Configuration only. Opting in before P4 is harmless: the flag is off. |
| The built-in egress list is left as it is | A placed seat's namespace gets an empty private allowlist (C5); nothing changes the default |

**Named follow-ons, not dropped:** one account per teammate; per-principal totals for CPU
and memory; per-seat resource bounds; a reconnect grace (Q1 of P1).

**Open:** Q1 of P1 (the dropped session). This plan builds option (a).

## Execution Policy

- execute: effort=high, reason=a new network-facing path that carries a review tree off the launching host and runs code on another machine
