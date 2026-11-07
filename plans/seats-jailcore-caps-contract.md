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
- resolution applies at every node, including nodes reached through `slaves`: a partition maps
  through `/sys/dev/block/MAJ:MIN/partition` to its parent, and resolution continues from that
  parent;
- a device-mapper node must have exactly one slave; resolution follows that slave and repeats until
  reaching a non-partition whole disk. This matches systemd's supported simple 1:1
  originating-device discovery and where it writes `io.max`, rather than the mapped device. A
  device-mapper node with zero or more than one slave, a cycle, or any otherwise unresolvable chain
  refuses;
- major 0 (tmpfs, overlay and other anonymous devices) has no block device to verify, so it cannot
  carry `io.max`. An automatic path (staging root or child scratch) on major 0 refuses explicitly:
  that host is unsupported for local seats until both sit on a block-backed filesystem. An
  `io_paths` entry never substitutes for an automatic path, and one on major 0 refuses too.

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

A local seat attempt creates exactly one transient capped parent cgroup, identified by its
`seat_key`, before any provider or worker target can run. `launch_owned`, `launch_provider`,
and every Capped site pass that same seat key to `capped_popen`. Each launch may use its own
transient child scope, but every such scope is a descendant of the one capped parent; a second
independent capped parent for the same live seat is a refusal. The parent remains live until
every child of the seat is reaped, then is collected.

| Class | Sites (function names at the base; successors after PANELSPLIT) |
|---|---|
| Capped | `_run_leg_with_liveness._popen`, `_run_claude_tui_session._popen`, and the SDK host worker start `_launch_claude_sdk_worker` once agent-harness#1866 lands (it starts its worker through `capped_popen` directly) |
| Exempt: short probes | identity probes, `_leg_auth_ok`, `_claude_subscription_auth_ok`, `_claude_code_support_status`, `_parent_auth_state`, `probe_grok_tools` |
| Exempt: not a seat | executor launches, `launcher.*`, `skill_eval_runner.*`, `convergence/adapters/base.run_bounded`, `output_retention.*`, `executor_availability.*`, `claude_agent_view.*` |
| Exempt: helpers and qualification | egress holder, slirp and bridge, the keyring helper, the jail qualification kit |

`capped_popen` first runs `load_caps`, `io_devices`, and `readiness_code`; a refusal raises
before any process starts. It creates or joins the seat's transient parent, starts the command
in a child scope beneath it, and runs the trusted `seat_resource_caps_enter` helper before the
target. The helper reads its cgroup membership, resolves the capped parent, and reads back
`memory.max`, `cpu.weight`, `cpu.max`, `io.weight`, `io.max` for every device, and `pids.max`
from that parent. Any absent or differing value exits without attesting, so the target never
runs. On EOF or the 15-second timeout, the launch and any empty parent are ended and reaped,
and `SeatSandboxRefused(CODE, ...)` is raised.

Child-side readback is the proof. A launcher status or accepted property submission is never
treated as evidence that a controller value took effect.

On a match the helper restores the exact caller-selected target environment, writes the
attestation byte, closes the pipe, and calls `execv`. The caller's process-group, descriptor,
working-directory, terminal, and teardown contracts remain unchanged. The SDK route's CLI and
host worker are separate launches beneath the same capped parent, so their combined use—not
each process independently—is bounded by one effective `seat_resource_caps.v1` record.

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

- **Binding.** `seat_resource_caps.v1` is the shared cap schema. A v13 local configuration loads
  it through §2, applies the documented v13 subset, and includes
  `seat_caps_sha256 = caps_sha256(effective_caps)` in the canonical host configuration hashed as
  `config_sha256`. `LocalHeadroomConfig` remains the pressure/headroom projection and does not
  define a second cap record.
- **Reservation.** The one capped parent per live `seat_key` is the SEATS equivalent of v13's
  per-reservation cgroup. When a coordinator reservation fronts the seat, the reservation and
  `seat_key` identify that same single parent; all provider and SDK-worker child scopes remain
  below it.
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
  owner, wrong mode) refuses and never falls back to defaults. A stricter root-managed record
  beside a wider operator record gives effective caps and `caps_sha256` from the managed record
  only; an unsafe managed record refuses and never falls through to the operator record.
- (c) Readiness: a tree without the unified hierarchy, without the user manager cgroup, without
  each `REQUIRED_CONTROLLERS` member in turn, without `systemd-run`, or without the bus socket
  each returns `CODE`; the complete tree returns `None`.
- (d) Devices: a whole disk, a partition mapped to its parent, and a stacked one-slave
  device-mapper chain containing an intermediate partition and resolving to its backing whole disk;
  a device-mapper node with zero or more than one slave, a cycle, and an otherwise unresolvable
  chain each refuse; major 0 refuses, including an automatic path on major 0 beside a block-backed
  `io_paths` entry.
- (e) Readback through the real helper: each §4 file absent or differing in turn, including
  `io.weight` and `io.max` absent while `memory.max` matches, writes no byte, and the target
  marker never runs.
- (f) `capped_popen` through the real helper: the returned pid is the target's pid, a passed
  descriptor survives, and the target's environment equals an uncapped launch's. A fake
  `systemd-run` that fails, hangs, or exits 0 without running the helper ends in `CODE`, with the
  process reaped and no target marker. Two concurrent launches for one fixture `seat_key`,
  including the CLI plus `_launch_claude_sdk_worker` shape, have distinct child scopes but the same
  capped parent; a mutation that creates two capped parents fails. A request for a second
  independent capped parent for a live `seat_key` refuses with `CODE` and starts no target.
- (g) Boundary: every row of `phase-loop-runtime/tests/data/seat_launch_references.json` with a
  process-start primitive in `panel_invoker` is classified by a table in the test, mirroring §4;
  an unclassified row fails, so a later launch site must choose. Each Capped site reaches
  `capped_popen`, path-entered. Mutation control: a capped site restored to raw `subprocess.Popen`
  fails. A `SeatJail` launch with no `seat_caps` refuses. The test requires the inventory tuple
  `(panel_invoker, _launch_claude_sdk_worker, subprocess.Popen)` or its named successor, so a role
  or filter change cannot exempt it. The path-entered SDK case asserts that
  `_launch_claude_sdk_worker` receives the live seat key, reaches `capped_popen`, and joins the
  CLI's capped parent; removing the key, bypassing `capped_popen`, or creating a second parent
  fails.
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
