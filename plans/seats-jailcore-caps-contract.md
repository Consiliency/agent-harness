# SEATS JAILCORE per-seat resource caps contract (IF-0-JAILCORE-4)

Frozen artifact for lane SL-5 of `plans/phase-plan-v1-seats-JAILCORE.md`. It carries the detail
the plan points at. Roadmap: `specs/phase-plans-seats-v1.md`, Phase 3, which this file does not
amend. A change to this file after the plan merges is a plan amendment.

Owner ruling, 2026-11-06 ("Pressure gates + per-sandbox caps"): local sandboxes must not swamp
a shared machine, in CPU or in disk bandwidth. This contract owns the per-seat caps half for
SEATS launches. The pressure gates are v13's (§6).

`plans/seats-jailcore-route-contract.md` is consumed unchanged, so its digest and every pin of
it stand. Nothing here changes `DESCEND_CODES`, `REMOTE_DESCEND_CODES`, `CAPACITY_CODES`, the
§3 security set, any walk rule, any profile digest or the qualification key.

## 1. The record

New module `phase_loop_runtime/seat_resource_caps.py`. The module's public shapes:

```python
SCHEMA = "seat_resource_caps.v1"
CODE = "seat_resource_caps_unavailable"
REQUIRED_CONTROLLERS = frozenset({"cpu", "io", "memory", "pids"})
MANAGED_RECORD = Path("/etc/consiliency/tooling/seat-resource-caps.json")

@dataclass(frozen=True)
class IoMax:
    rbps: int
    wbps: int
    riops: int
    wiops: int

@dataclass(frozen=True)
class SeatResourceCaps:
    schema: Literal["seat_resource_caps.v1"]
    memory_max_bytes: int
    cpu_weight: int
    cpu_max_percent: int          # 100 is one whole CPU; period fixed at 100000 usec
    io_weight: int
    io_max: IoMax                 # applied to every device of io_paths
    io_paths: tuple[str, ...]     # extra absolute paths; see "io devices"
    pids_max: int

def load_caps() -> SeatResourceCaps                    # §2; raises on refusal
def caps_sha256(caps: SeatResourceCaps) -> str         # sha256 of canonical JSON, sorted keys
def io_devices(caps: SeatResourceCaps) -> tuple[str, ...]  # "MAJ:MIN"; raises on refusal
def readiness_code() -> str | None                     # §3; None or CODE
def capped_popen(command, *, seat_key: str, **popen_kwargs) -> "subprocess.Popen[bytes]"  # §4
```

Packaged defaults. Each row is a finite limit below the host's default share, chosen so several
seats leave the rest of a shared host running. Hosts tune them through §2.

| Field | cgroup file | systemd property | Default |
|---|---|---|---|
| `memory_max_bytes` | `memory.max` | `MemoryMax` | 4294967296 (4 GiB) |
| `cpu_weight` | `cpu.weight` | `CPUWeight` | 50 (half the default share) |
| `cpu_max_percent` | `cpu.max` | `CPUQuota` | 200 (two CPUs: `200000 100000`) |
| `io_weight` | `io.weight` | `IOWeight` | 50 (half the default share) |
| `io_max.rbps` | `io.max` | `IOReadBandwidthMax` | 104857600 (100 MiB/s) |
| `io_max.wbps` | `io.max` | `IOWriteBandwidthMax` | 52428800 (50 MiB/s) |
| `io_max.riops` | `io.max` | `IOReadIOPSMax` | 2000 |
| `io_max.wiops` | `io.max` | `IOWriteIOPSMax` | 1000 |
| `pids_max` | `pids.max` | `TasksMax` | 512 |
| `io_paths` | — | — | `()` |

`io.max` is the binding disk limit. `io.weight` is a relative share that only takes effect where
the device's scheduler or the host's IO cost model honours it; it is set and read back, but no
test claims a bandwidth effect from it.

**io devices.** `io_devices` is the deduplicated device set backing, in order,
`sandbox_policy.staging_root()` (staged trees), the child scratch directory and each `io_paths`
entry. A host whose workspace volume differs from its staging root lists that volume in
`io_paths`. Each path resolves through `os.stat(path).st_dev`:

- a partition maps to its whole disk, through `/sys/dev/block/MAJ:MIN/partition` and the parent
  directory, because `io.max` takes whole devices only;
- a device-mapper device is used as it is;
- major 0 (tmpfs, overlay and other anonymous devices) cannot carry `io.max`: refusal, and the
  fix line names `io_paths`.

## 2. Host sources

First match wins:

1. `MANAGED_RECORD`, when present. Root-owned, not group or world writable, read through the
   private-file read used for the pass store. An operator record is not read on such a host,
   because seats there share one machine.
2. `<state_home>/phase-loop/seat-resource-caps.json`, under the same ownership and mode checks as
   the pass store (`pass_store_dir_problem`, private file read).
3. The packaged defaults.

A record is a JSON object holding `schema` and any subset of the §1 fields; absent fields take
the packaged default. These rules hold for both files:

- Unknown keys, duplicate keys, trailing data, an unsafe file and a value outside its bound all
  refuse with `CODE`. Unlike the route-policy overlay (route contract §6), a bad record is never
  ignored: ignoring it would run limits the operator did not set.
- No value expresses "no limit". The literal `max`, zero, negatives, booleans, floats and
  strings refuse.
- Bounds: `memory_max_bytes` at least 268435456 and at most `MemTotal`; both weights 1–10000;
  `cpu_max_percent` at least 10 and at most 100 × online CPUs; every `io_max` value at least 1;
  `pids_max` at least 16; every `io_paths` entry absolute.

No environment variable, flag or argument selects a record or disables enforcement.

## 3. Readiness and the route

`readiness_code()` returns `CODE` unless all of these hold, all read under an injectable
cgroupfs root and sysfs root:

1. The unified hierarchy: the root `cgroup.controllers` file exists.
2. The operator's user manager cgroup,
   `user.slice/user-<uid>.slice/user@<uid>.service`, lists every `REQUIRED_CONTROLLERS` member in
   `cgroup.controllers`.
3. `/usr/bin/systemd-run` is a root-owned executable, and the user manager's bus socket exists
   under `XDG_RUNTIME_DIR`.
4. `load_caps()` and `io_devices()` succeed.

The route uses the contract's existing shape. `seat_profiles.register` stores every profile with
`Precondition("resource_caps", <readiness_code>)` last in `preconditions` and `CODE` in
`notice_codes`, so CODEX, GROK, PI and any later profile carry it with no edit of their own. The
check therefore runs inside step L6 and needs no new walk step. `preconditions` is not an input
to `jail_profile_digest`, so EC-JAILCORE-1 still holds.

A leg with no profile leaves the walk at L1 under an unconfined exception, so step L6 does not
run for it. The launch boundary (§4) covers that leg: it ends with `CODE` as a terminal refusal
(route contract W5), and nothing launches.

## 4. Enforcement at the launch boundary

Seat start sites call `launch_owned` or `launch_provider` with a new keyword, `seat_caps=<seat
key>`. With it set, `launch_provider` starts the provider through `capped_popen` in place of
`subprocess.Popen`, at both the jailed and the owned start. A `SeatJail` owner with no
`seat_caps` refuses with `CODE`. Other `launch_provider` callers are unchanged, because the
function also serves executors and helpers.

| Class | Sites (function names at the base; successors after PANELSPLIT) |
|---|---|
| Capped | `_run_leg_with_liveness._popen`, `_run_claude_tui_session._popen`, and the SDK host worker start `_launch_claude_sdk_worker` once agent-harness#1866 lands (it starts its worker through `capped_popen` directly) |
| Exempt: short probes | identity probes, `_leg_auth_ok`, `_claude_subscription_auth_ok`, `_claude_code_support_status`, `_parent_auth_state`, `probe_grok_tools` |
| Exempt: not a seat | executor launches, `launcher.*`, `skill_eval_runner.*`, `convergence/adapters/base.run_bounded`, `output_retention.*`, `executor_availability.*`, `claude_agent_view.*` |
| Exempt: helpers and qualification | egress holder, slirp and bridge, the keyring helper, the jail qualification kit |

`capped_popen` runs these steps:

1. `load_caps`, `io_devices` and `readiness_code`. A refusal raises before any process starts.
2. It creates one attestation pipe and spawns
   `systemd-run --user --scope --quiet --collect --unit=phase-loop-seat-<nonce>.scope <-p
   properties> -- <helper> <expected values> -- <command>`, with the helper built by
   `seat_uid.trusted_module_argv("phase_loop_runtime.seat_resource_caps_enter", ...)`. The scope
   is outermost, in front of every namespace entry.
3. It waits up to `SCOPE_ENTER_TIMEOUT_S = 15` for one byte on the pipe. On EOF or timeout it ends
   the process group, reaps it and raises.
4. It returns the `Popen`.

`seat_resource_caps_enter` is a stdlib-only module. It reads its cgroup from `/proc/self/cgroup`
and reads back `memory.max`, `cpu.weight`, `cpu.max`, `io.weight`, `io.max` (one line per
device) and `pids.max`. Any missing or differing value exits without writing the byte, so the
provider never runs. Readback is the proof, not the `systemd-run` exit status: `systemd-run`
exits 0 and leaves `io.weight` and `io.max` absent when the `io` controller is not delegated,
measured on systemd 259.

On a match it restores the environment the caller decided, byte for byte. `systemd-run` needs
the bus location and adds `INVOCATION_ID`, and neither may reach the chain unless the caller's
environment already held it. It then writes the byte, closes the pipe and calls `execv`.

Scope mode runs the command in place, so the `Popen` pid, process group, session, inherited
descriptors, working directory and terminal stay the caller's (measured). Existing teardown and
`--die-with-parent` are unaffected. The refusal is `seat_jail.SeatSandboxRefused(CODE, ...)`,
which `panel_invoker` already classifies, and a leg's failure detail carries the code.

Each launch gets its own scope, and the scope ends with its last process. One seat has one live
launch, with one exception: the SDK route's CLI and host worker each run in a scope under the same
record, so that route's ceiling is twice the record. A cap breach ends or fails the process
through the leg's existing exit path; there is no new post-launch code.

## 5. Refusal code

`seat_resource_caps_unavailable` is one `seat_jail.NOTICES` entry with one
`seat_route_contract.OD10_CLASSES` entry, class `ordinary`, following the additive rule of route
contract §1 and §3. It is terminal: it joins no descend set, so W1 gives mode `degraded`, and no
remote or native-fill rung is entered. A seat that cannot be capped does not run, and there is no
fallback. It stays out of `seat_route_contract.CODES`, so the §4 table and the literal security
set are unchanged.

The notice's fix line names the host prerequisite (§8) and the record file. The specific cause
goes to the private operator log.

## 6. Consistency with v13 placement

Cited at agent-harness#1853 head `497b6402`, which is open at this freeze: v13 principle 9,
`XREQ-SEATS-LOCAL-CGROUP-1`, EC-PLACECLI-5, and the `local_cgroup_execution` rule of
`plans/artifacts/v13-PLACECLI-contract-v1.schema.json`. SL-5 re-reads these by ID before it
starts. If a cited ID changed meaning, SL-5 STOPs and reports the exact sentence.

**One schema; v13's caps are a documented subset of `seat_resource_caps.v1`.**

| v13 cap | Field here |
|---|---|
| `memory.max` | `memory_max_bytes` |
| `cpu.weight` | `cpu_weight` |
| `io.weight` or `io.max` | `io_weight` and `io_max`; SEATS sets both, which satisfies "either" |
| (not in v13) | `cpu_max_percent`, `pids_max`, `io_paths` |

- **Binding.** `caps_sha256` is canonical over the effective record, so v13's host
  `config_sha256` can bind it by value. v13's `LocalHeadroomConfig` has no cap field at this
  freeze; these caps are the record for it to adopt.
- **Reservation.** One scope per launch is at least as narrow as v13's per-reservation cgroup.
- **Refusal.** The SEATS route code is `CODE`. When a coordinator reservation fronts a local
  seat launch, that client reports the same refusal as `sandbox_placement_capability_unmet`.
  That mapping lands with the first coordinator-routed local seat launch and is not part of
  SL-5. Both mean nothing launched.
- **Pressure.** Host admission thresholds stay with EC-PLACECLI-5. SL-5 adds no pressure check.

## 7. Test obligations

`phase-loop-runtime/tests/test_seat_resource_caps.py`, on a fake cgroupfs and sysfs tree and a
fake `systemd-run` executable:

- (a) Defaults equal the §1 table literally, and every field is finite.
- (b) Record sources: managed wins and suppresses the operator file; operator overrides apply;
  each §2 rejection (unknown key, `max`, zero, negative, boolean, float, out of bound, link, wrong
  owner, wrong mode) refuses and never falls back to defaults.
- (c) Readiness: a tree without the unified hierarchy, without the user manager cgroup, without
  each `REQUIRED_CONTROLLERS` member in turn, without `systemd-run`, or without the bus socket
  each returns `CODE`; the complete tree returns `None`.
- (d) Devices: a whole disk, a partition mapped to its parent, a device-mapper device, and major 0
  refusing.
- (e) Readback through the real helper: each §4 file absent or differing in turn, including
  `io.weight` and `io.max` absent while `memory.max` matches, writes no byte, and the target
  marker never runs.
- (f) `capped_popen` through the real helper: the returned pid is the target's pid, a passed
  descriptor survives, and the target's environment equals an uncapped launch's. A fake
  `systemd-run` that fails, hangs, or exits 0 without running the helper ends in `CODE`, with the
  process reaped and no target marker.
- (g) Boundary: every row of `phase-loop-runtime/tests/data/seat_launch_references.json` with a
  process-start primitive in `panel_invoker` is classified by a table in the test, mirroring §4;
  an unclassified row fails, so a later launch site must choose. Each Capped site reaches
  `capped_popen`, path-entered. Mutation control: a capped site restored to raw `subprocess.Popen`
  fails. A `SeatJail` launch with no `seat_caps` refuses.
- (h) Route, through `_seat_route_for_spawn`, with recording rungs: a refusing host gives
  `degraded` with `CODE` at L6, and neither rung is entered. `CODE` is in no descend set, its
  `OD10_CLASSES` class is `ordinary`, and a synthetic profile carries the precondition with no
  edit. `jail_profile_digest` is unchanged for `claude` and `gemini`.
- (i) A source scan finds no environment read or flag in `seat_resource_caps.py` that disables
  enforcement, paired with case (c): the environment of a refused launch cannot make it proceed.

The other test files need the same no-op, so the autouse fixture in
`phase-loop-runtime/tests/conftest.py` replaces `readiness_code` and `capped_popen` by
monkeypatch. Tests marked `real_seat_caps` opt out. Production has no equivalent switch.

**Host probe.** `test_seat_resource_caps.py -k host_probe`, opt-in through
`PHASE_LOOP_SEAT_CAPS_PROBE=1`. It skips when not opted in or when `readiness_code()` refuses.
Through real `systemd-run`, it asserts the readback, then that a direct write and a buffered
fsynced write of 4 MiB each take at least one second under a 2 MiB/s `io.max`, that a 64 MiB
`memory.max` ends a larger allocation, and that a 16 `pids.max` refuses further forks. Each probe
is small and self-throttled, so it is safe on a shared host.

## 8. Host prerequisite

A stock `user@.service` delegates `pids memory cpu`, without `io`. Hosts that run review seats
need this root-owned drop-in at `/etc/systemd/system/user@.service.d/delegate.conf`:

```ini
[Service]
Delegate=cpu cpuset io memory pids
```

It takes effect after `systemctl daemon-reload`, and on some hosts only once the operator's user
manager restarts. `io` listed in the manager's `cgroup.controllers`, and a passing host probe, are
the proof; this contract does not assume the timing. `docs/seat-resource-caps.md` states this,
the record and the probe.

Until the drop-in is live, `readiness_code()` refuses and every local seat on that host is
degraded, so this prerequisite orders SL-5's landing: see the plan's host gate.
