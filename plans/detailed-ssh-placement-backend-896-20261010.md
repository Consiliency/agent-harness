---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1246, agent-harness#1162]
builds_on: plans/detailed-remote-seat-placement-896-20261010.md
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_sandbox_ssh.py tests/test_placement_entry.py tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_seat_notices.py tests/test_seat_reference_inventory.py tests/test_gate_a_wheel_isolation.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: an `ssh` placement backend and its compute-host entry point, proven with a null workload (agent-harness#896, P2)

## Task

The maintainer ruled on 2026-10-10 that review seats move to a self-hosted compute host
over SSH first. This unit is the transport and the far end: an `ssh` `ExecutingBackend`
behind the placement seam, and the entry point it talks to on the compute host. It stages a
tree there, verifies it, runs a **null workload**, and cleans up. It runs no vendor CLI and
carries no credential; P3 (`plans/detailed-remote-seat-execution-896-20261010.md`) adds the
seat.

The seam, its amendments C1–C9 and the driver are in
`plans/detailed-remote-seat-placement-896-20261010.md` (P1). This plan cites them and
restates none.

**General product.** Nothing here names a host, an account, an address or a tailnet. The
destination is configuration. Development and CI need no particular host: every test runs
against a throwaway `sshd` on loopback, or against the entry point over a pipe.

## Research summary

- **The seam.** A backend registers under a URL scheme through the entry-point group
  `phase_loop_runtime.placement_backends`, loaded only when a configured root names that
  scheme (`sandbox_placement._load_plugins`, `backend_for_scheme`). The package's own
  `pyproject.toml` already declares entry points of this kind for other groups.
- **Roots.** `sandbox_policy.parse_location` keeps a URL root's scheme, host, port and path
  and drops userinfo at parse. An `ssh` root therefore cannot carry an account name; the
  account comes from the operator's SSH client configuration for that destination.
- **The only SSH on main** is the legacy `host:path` probe in `sandbox_policy` (`_probe_root`,
  `_free_bytes_at`). It is record-only (ruling RD6 (a)) and is not touched.
- **Local sandbox pieces the far end reuses unchanged:** `sandbox_egress.isolated_network`
  and `host_addresses` (a seat's namespace rejects every address of the host it runs on,
  before any allowlisted endpoint); `review_stage.review_tree_manifest_sha256`;
  `sandbox_retention`; `seat_jail_prerequisites.check`.
- **Launch inventory.** `tests/data/seat_launch_references.json` pins launch primitives per
  module and function; a module that starts `ssh` adds rows. A launch made under the
  runtime's infrastructure marker is not counted as a provider spawn.
- **Packaging.** Package data is enumerated in `pyproject.toml` (`deploy/*.service` today).

## Design

**Root.** `ssh://<destination>[:<port>]`, with an empty path. `<destination>` is a host
name or an alias in the operator's SSH client configuration, which also supplies the
account and the key. A root with a non-empty path is refused (`sandbox_ssh_root_invalid`).

**One session per sandbox; the session is the lease.** `admit` starts the host's `ssh`
client and holds the session until `release`. The far end kills the sandbox and removes its
directory when the session ends for any reason: end of input, a cancel, or no frame within
its lease time. An owner that dies therefore cannot leave a sandbox running.

**The cost of that choice, accepted for this slice.** A session that drops for any reason,
a network interruption included, ends the seat: after launch that is
`sandbox_placement_lost_after_launch`, with no fallback, however long the seat had been
running. The far end holds nothing to reconnect to. A reconnect grace (hold the sandbox for
the lease time and accept a resume bound to a nonce) is a deliberate follow-up, not part of
this unit; the first measurements on a real path decide whether it is needed.

**The client forces what it can.** Fixed arguments on every invocation: no terminal, batch
mode, no agent, X11 or port forwarding, no connection sharing, no local command, strict
host-key checking, a bounded connect time, and keep-alives. The remote command is the fixed
string `phase-loop-seat-entry placement_ssh.v1 <runtime version>`. The child's environment
is a fixed short list. Its stderr goes to the private leg log and never into a detail.

**Wire protocol `placement_ssh.v1`.** Length-prefixed frames with a size cap. Control frames
are JSON with a closed key set; the stage, the request and the result are bytes.

| Seam call | Frames |
|---|---|
| `admit` | `HELLO` (protocol, runtime version, wheel `RECORD` digest, owner id, stage size, nonce) → `READY` (report, below) or `REFUSED` (code, retryable) |
| `commit` | `STAGE` chunks, `STAGE_END` (digest) → `COMMITTED` (sandbox ref, digest as recomputed there) or `REFUSED` |
| `execute` | `EXECUTE` (kind, request bytes) → `STARTED` |
| `wait` | `PROGRESS` (seq) … `RESULT` (exit status, result bytes, truncated) |
| `renew` | `RENEW` → `ACK` |
| `cancel`, `release`, `kill` | `CANCEL` → `KILLED`, then the session closes |
| `list_owned`, and `kill` with no open session | a second, short session: `LIST` / `KILL` (owner id) |

**Admission codes** (each a `NOTICES` row with a fix line):
`sandbox_ssh_root_invalid`, `sandbox_ssh_client_missing`, `sandbox_ssh_unreachable`,
`sandbox_ssh_protocol_mismatch`, `sandbox_ssh_runtime_unavailable`,
`sandbox_ssh_host_unqualified`, `sandbox_ssh_capacity` (retryable),
`sandbox_ssh_below_floor`, `sandbox_ssh_snapshot_mismatch`.

**The far end.**
- **A root-owned shim** (`deploy/phase-loop-seat-entry.sh`, POSIX `sh`, shipped as package
  data) is what the SSH server runs, as a forced command or as the account's login shell. It
  accepts exactly the fixed command string, maps the version to an installed runtime
  directory, and executes that runtime's entry point with the principal name the server
  configuration gave it. Any other request, or a version that is not installed, exits with
  a fixed status and runs nothing.
- **The entry point** (`placement_entry.py`, console script `phase-loop-seat-entry`):
  - reads one root-owned configuration file with a closed key set (workspace, concurrency
    caps overall and per principal, free-space floor, lease time, arrival rule), and
    refuses to run if the file is missing, not root-owned, or writable by anyone else;
  - **arrival rule:** refuses a session that arrived on a globally routable address,
    unless the file says otherwise. This is how "never on a public interface" is checked;
  - **runtime identity:** refuses unless its own version and wheel digest equal `HELLO`'s;
  - **capacity:** a slot lock per running sandbox; at a cap it refuses, retryable;
  - **stage:** a private directory per principal and sandbox (0700). Extraction refuses
    absolute names, parent references, hard links, devices and anything that would land
    outside the directory, and never follows a link. The digest is recomputed with
    `review_tree_manifest_sha256`; a mismatch refuses and removes the partial state;
  - **isolation between principals:** `LIST` and `KILL` see only the caller's principal and
    owner id; any other reference is "not found";
  - **restart safety:** each sandbox directory holds a lock owned by its session's process.
    At every start the entry point removes its principal's directories whose lock is free.
- **Host qualification, on the host, per boot.** The entry point keeps a verdict for its
  runtime version and the current boot. With none, it runs the probe before `READY`:
  - from inside a network namespace built exactly as a seat's is, a TCP connection to every
    listening port on every address of the host fails;
  - the session's resource group has memory, CPU and task limits;
  - no device other than the standard pseudo-devices and the tunnel device can be opened;
  - `seat_jail_prerequisites.check` reports nothing missing.

  A failed probe refuses every admission with `sandbox_ssh_host_unqualified` until it
  passes. A reboot, or a new runtime version, runs it again. `READY` carries the verdict
  and the measured values.
- **`kind="null"`** returns the probe report as its result. **`kind="leg"`** is refused in
  this unit.

**Capabilities.** The backend declares `inbound_closed`, `one_shot_secret_channel`,
`private_ranges_unreachable`, `private_allowlist`, `public_egress`, `filesystem_confined`
and `resource_bounded`. Each is recorded as `backend_attested`, from `READY`. Nothing is
`runtime_end_to_end` in this unit.

**What SSH does about the maintainer's 2026-10-04 requirements on agent-harness#896.**
Those requirements were written for the HTTPS service and stay attached to it. For this
backend:

| Requirement | This backend |
|---|---|
| Reachable only over the tailnet; qualification refuses a public listener | **Met differently:** the arrival rule above, plus deployment (the port is offered only on a private interface). The launching side cannot inspect the server's listeners. |
| A per-principal credential **and** a verified allowed source | **Met differently, by deployment:** one SSH key per user, pinned by the server to the launching host's address. No reusable secret crosses the wire. The product ships the guidance, not the server configuration. |
| One principal per account on a shared launching host; easy issue and revoke | **Met:** the principal is the name the server configuration binds to each key. |
| Per-principal isolation by separate uid ranges | **Open, B6.** One account on the compute host means separation by the entry point's per-principal workspace and the seat's filesystem view. |
| Per-principal caps: concurrent sandboxes | **Met.** |
| Per-principal caps: total CPU and memory | **Not met in this slice; needs an explicit waiver.** One limit bounds the whole account. |
| Later: signed requests | **Already met** by SSH keys. |

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_ssh.py` (create)
- `SshBackend` — add — the `ExecutingBackend` above. It resolves `ssh` with
  `review_stage.trusted_host_executable` (no change needed there: it resolves any name
  from the trusted directories) and starts it under the infrastructure-launch marker.
- `register()` — add — registers it under the scheme `ssh`.
- The frame codec — add — shared with `placement_entry`.

### `phase-loop-runtime/src/phase_loop_runtime/placement_entry.py` (create)
- `main()` — add — the entry point above: configuration, arrival rule, identity, capacity,
  stage, null workload, lifecycle, `LIST` / `KILL`, the per-boot host qualification.

### `phase-loop-runtime/src/phase_loop_runtime/deploy/phase-loop-seat-entry.sh` (create)
- The shim — add.

### `phase-loop-runtime/pyproject.toml` (modify)
- `[project.entry-points."phase_loop_runtime.placement_backends"]` — add — `ssh`.
- `[project.scripts]` — add — `phase-loop-seat-entry`.
- `[tool.setuptools.package-data]` — modify — `deploy/*.sh`.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `sandbox` command, action `qualify <name>` — add — drives a null workload over a small
  synthetic tree through P1's driver against the named root (ask B4 of the E2B plan: one
  path, no parallel one). It also opens a second session and kills its own client
  mid-workload, then checks through `LIST` that nothing is left. It prints the report and
  exits non-zero if any property fails. Its record never counts as an applied placement.

### `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `panel_invoker.py` (modify)
- `NOTICES` and `_HARNESS_DETAIL_CODES` — modify — the nine admission codes, added the way
  each closed list already grows.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … a HARNESS CODE — a fixed string this
  runtime itself emits (`_HARNESS_DETAIL_CODES`)". Nine members are added by that
  mechanism, and no template or category.

### `phase-loop-runtime/tests/test_sandbox_ssh.py`, `tests/test_placement_entry.py` (create); `tests/data/seat_launch_references.json`, `tests/test_seat_notices.py` (modify)
- The falsifiers under "Verification"; the new launch rows for `sandbox_ssh`.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — an "SSH
  placement backend" subsection under the placement seam: the root form, the session as
  lease, the protocol table, the codes, the entry point's refusals.
- `docs/phase-loop/remote-seat-host.md` — create — operator guide for a compute host: the
  account, the forced command or login shell, one source-pinned key per user, the
  configuration file, resource limits, an output firewall for the account, installing the
  runtime per version, `sandbox qualify`. Example names and addresses use documentation
  ranges only.
- `docs/phase-loop/convergence-runtime.md` — modify — the `ssh` root form.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none.

## Dependencies & order
1. Needs P1 merged (amendments C1–C9, the driver, `phase-loop sandbox`).
2. No agy route-core file is edited.
3. Order: the frame codec and its tests; the entry point over a pipe; the backend against
   the loopback `sshd` fixture; `qualify`; packaging.
4. The compute host's account, limits, firewall and network grant are deployment work
   outside this repository. Nothing in this unit waits on them, and nothing here performs
   them.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_sandbox_ssh.py tests/test_placement_entry.py tests/test_placement_driver.py \
  tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_seat_notices.py \
  tests/test_seat_reference_inventory.py tests/test_gate_a_wheel_isolation.py
ruff check .
```

Run on Python 3.12 and 3.10. Two fixtures: the entry point driven over a pipe, and a
throwaway `sshd` on loopback (own host key, own `authorized_keys`, a forced command) that
skips with a stated reason where `sshd` is not installed. At least one test in each group
below goes through the real `ssh` client. Each case is control-green and red under its
mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Null workload through the driver | `admit`, `commit`, `execute`, `wait`, `release` in order; zero local provider spawns; the far end's recomputed digest equals the runtime's | Skip the recompute |
| One byte of the stage altered in transit | `sandbox_ssh_snapshot_mismatch`; no directory remains on the far end | Compare the digest the client sent with itself |
| Archive with an absolute name, a parent reference, a hard link, a device, a link pointing outside | Refused; nothing written outside the sandbox directory | Use the archive library's default extraction |
| Client killed with SIGKILL mid-workload | The far end's workload is gone and its directory removed within the lease time; a later `LIST` is empty | End the workload only on `CANCEL` |
| Entry point killed mid-workload, then a new session | The stale directory is removed at start | Skip the start sweep |
| Session open, no frame for longer than the lease time | Killed and removed | Renew on a timer at the far end |
| At the overall cap, and at the per-principal cap | `sandbox_ssh_capacity`, retryable; another principal below its cap is admitted | Count sandboxes across principals for the per-principal cap |
| `LIST` and `KILL` for another principal's sandbox | "Not found"; the sandbox survives | Drop the principal filter |
| Runtime version or wheel digest differs | `sandbox_ssh_runtime_unavailable` or `sandbox_ssh_protocol_mismatch`; nothing staged | Compare versions only |
| The shim, given any other command string, a version with a path separator, or no command | Fixed non-zero exit; the entry point is not executed | Pass the string to a shell |
| Configuration file missing, not root-owned (simulated by an owner check seam), or group-writable | The entry point refuses before reading a frame | Read it anyway |
| Session arriving on a globally routable address | Refused | Trust the client's claim |
| Host probe: a listener the fixture opens on a host address | Verdict fails; every admission is `sandbox_ssh_host_unqualified` until it is closed and the probe re-run | Probe loopback only |
| Host probe: no limits on the session's resource group | Verdict fails | Report limits without reading them |
| Forced client options | The recorded argument list carries every option listed under Design, with the operator's own configuration asking for forwarding and connection sharing | Drop one option |
| Root with a path, with userinfo, with a query | Refused, or the userinfo and query absent from the argument list | Pass the configured text |
| `sandbox qualify` against the loopback fixture | Exit 0 and a complete report; exit non-zero when the fixture's entry point is made to fail one property | Exit 0 on a partial report |
| `kind="leg"` | Refused in this unit | — |

## Acceptance criteria
- [ ] `phase-loop sandbox qualify <name>`, run against the loopback `sshd` fixture through
  the real `ssh` client, exits 0 with zero local provider spawns and a digest recomputed by
  the far end; with one byte of the stage altered it reports
  `sandbox_ssh_snapshot_mismatch`.
- [ ] A client killed with SIGKILL mid-workload leaves, within the lease time, no workload
  and no sandbox directory on the far end.
- [ ] With a listener opened on one of the fixture host's addresses, every admission is
  refused with `sandbox_ssh_host_unqualified`.
- [ ] Every test in `automation.suite_command` passes on a machine with no network access
  beyond loopback, and the new product files contain no IPv4 literal outside loopback.

## Maintainer decisions

**Settled, cited:** the route (2026-10-10); RD6 (b) is exercised by this backend.

**Open, and what this plan assumes until they are ruled:**

| ID | Question | Assumed here | If ruled otherwise |
|---|---|---|---|
| B5 | Dedicated SSH port with a forced command and per-user keys, or the tailnet's own SSH with a login shell | Either: the shim serves both, and the principal is whatever the server binds | Under the tailnet's own SSH every user of a shared launching host is one identity, so a per-principal token must be added to `HELLO` |
| B6 | One account on the compute host, or one per user | One | Per-user accounts need no code change; the per-principal workspace then sits inside each account |
| — | Waiver: per-principal totals for CPU and memory are not in this slice | Waived | A resource group per principal is added to the entry point |

## Execution Policy

- execute: effort=high, reason=a new network-facing path that carries a review tree off the launching host and runs code on another machine
