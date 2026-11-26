# Per-seat resource caps

Local review seats fail closed unless the runtime can put every provider process and SDK
worker for one scoped seat attempt below one capped cgroup parent. Each process uses a
distinct child scope, so the record limits their combined use. Overlapping board,
qualification and conformance attempts get separate parents even when they use the same
logical `seat_key`. LaneExec keeps its reservation-derived slice. A failed setup or readback reports
`seat_resource_caps_unavailable`; the seat does not run and has no uncapped fallback.

Each attempt's cap counts toward the account's overall memory limit. With the default 4 GiB
cap and zero swap, two overlapping attempts can exceed the dev0 collaborator account's 6 GiB
limit. A single board with several concurrent capped legs can already exceed 6 GiB.
Serialize capped legs and attempts on that account, and use a separately provisioned runner
for overlap tests. Cross-user admission and raised caps are tracked in agent-harness#2197.

The runtime records each private slice's owner PID, process start time and boot ID under
`$XDG_RUNTIME_DIR/phase-loop-seat-owners`. Normal collection stops and drains the exact
slice, then removes its runtime overrides. Board launches, qualification and conformance
can also collect records for their respective class after verifying that the original owner
has exited. Unverifiable owners are left in place. The readiness report includes advisory
stale and unknown record counts.

## Effective record

The schema is `seat_resource_caps.v1`. First match wins:

1. `/etc/consiliency/tooling/seat-resource-caps.json`, when present. It must be a root-owned
   regular file and not group- or world-writable.
2. `$XDG_STATE_HOME/phase-loop/seat-resource-caps.json` (normally
   `~/.local/state/phase-loop/seat-resource-caps.json`). Its directory chain and file must be
   private to the operator.
3. The packaged finite defaults.

The managed record suppresses the operator record. An unsafe, malformed or out-of-bounds
record refuses; it never falls through. Records may contain `schema` and any subset of these
fields:

| Field | Packaged default |
|---|---:|
| `memory_max_bytes` | 4294967296 (4 GiB) |
| `cpu_weight` | 50 |
| `cpu_max_percent` | 200 (two CPUs) |
| `io_weight` | 50 |
| `io_max.rbps` | 104857600 (100 MiB/s) |
| `io_max.wbps` | 52428800 (50 MiB/s) |
| `io_max.riops` | 2000 |
| `io_max.wiops` | 1000 |
| `io_paths` | `[]` |
| `pids_max` | 512 |

Every value is finite. Unknown or duplicate keys, trailing data, `max`, zero, negative,
boolean, floating-point or out-of-bound values refuse. `io_paths` contains additional
absolute paths whose whole backing block devices receive the same `io.max` values. A
partition resolves to its whole disk. A device-mapper node must resolve through exactly one
slave at every layer. `memory_max_bytes` should be page-aligned; a kernel-rounded readback
does not match the requested record and therefore refuses. Every capped parent also sets
`MemorySwapMax=0`, and the child must read back `memory.swap.max` as exactly `0`; a host that
cannot expose or enforce that file refuses with `seat_resource_caps_unavailable`.

The staging root and child scratch are automatic I/O paths. A major-0 filesystem normally
refuses because no block device can carry `io.max`. The runtime recognizes a descriptor-opened
`tmpfs` only when mountinfo and `fstatfs` agree, but currently refuses that carve-out because
the staging lifecycle does not yet remove launch-created content before parent collection.
An operator `io_paths` entry is never eligible for a carve-out. Until the cleanup wiring lands,
every automatic tmpfs path fails closed with `seat_resource_caps_unavailable`.

## Memory telemetry

The runtime baselines the capped parent before starting a local child, samples once
per second, and samples again at leg finalization. The private `leg_exec.v1` record and
each streamed verdict include an optional `seat_memory` object. It reports the
parent's effective cap and peak in bytes, deltas for the hierarchical `max`, `high`,
`oom`, and `oom_kill` counters, the parent's `local_max` delta, and cumulative
`some_stall_us` and `full_stall_us` deltas from Linux memory pressure totals.

`peak_source` is `kernel` for a fresh, empty, exclusively attributable parent with
a zero peak at baseline and a continuous cgroup identity. An existing parent or
inaccessible kernel peak falls back to the largest observed `memory.current`
(`sampled`, a lower bound). Missing values are null.
The state is `final` when every launched scope has a positive drain witness and the
terminal sample is complete and attributable. `partial` retains usable readings
when any part of the observation is incomplete or attribution is uncertain.
`unavailable` means there were no usable measurements. Unlaunched and nonlocal
legs omit the object.

The runtime logs `seat_memory_max_reached` at most once during an attempt. The
board carries it as a typed seat notice, and the streamed verdict includes it as
`seat_memory_notice`. The condition is
a positive parent-local `max` delta with more than 1,000,000 microseconds of full
memory stall, or any attributable `oom` or `oom_kill` delta. A hierarchical `max`
delta alone remains a metric. The telemetry does not change the launch decision
or its cleanup outcome.

## Host prerequisite

The operator's systemd user manager must delegate `cpu`, `cpuset`, `io`, `memory` and `pids`.
Install this root-owned drop-in as
`/etc/systemd/system/user@.service.d/delegate.conf`:

```ini
[Service]
Delegate=cpu cpuset io memory pids
```

Run `systemctl daemon-reload`. A user manager that started before this delegation was installed
must be reexecuted with `systemctl --user daemon-reexec` (or fully restarted): systemd snapshots
its supported-controller mask when that manager starts, and `daemon-reload` does not refresh the
mask. Before a host probe, verify that
`io` appears in `user.slice/user-<uid>.slice/user@<uid>.service/cgroup.controllers`. The launch
boundary realizes an empty capped parent and verifies controller propagation through every slice
level before it starts the child; an unavailable controller fails early with
`seat_resource_caps_unavailable`. The runtime also requires root-owned executable
`/usr/bin/systemd-run` and the user's runtime bus socket.

## Designated-host probe

The opt-in probe module is
`phase-loop-runtime/tests/test_seat_resource_caps.py`. From a source checkout whose pinned
test environment is installed, run:

```sh
PHASE_LOOP_SEAT_CAPS_PROBE=1 \
PYTEST_ADDOPTS= \
PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" \
timeout 300 phase-loop-runtime/.venv/bin/python -m pytest -p no:cacheprovider -q \
phase-loop-runtime/tests/test_seat_resource_caps.py -k host_probe
```

The probe skips by default. Once enabled, it fails if delegation or another seat-cap
readiness prerequisite is missing. The probe makes no provider call.

## CI and hosted runners

`publish-pypi.yml` runs the agy release gate inside a systemd user manager on an ephemeral
hosted runner, so the gate needs the same host prerequisite as a seat host. Hosted runner
pools differ in storage layout, and an automatic scratch path that does not resolve to a
whole block device fails readiness with `seat_resource_caps_unavailable`
(agent-harness#1993). `ci/seat-caps-host.sh` therefore prepares every runner the same way:

- `delegate` installs the delegation drop-in above, enables lingering, restarts the user
  manager, waits for its bus and checks the delegated controllers.
- `provision` creates a private, sparse, 8 GiB loop-backed ext4 filesystem under
  `$RUNNER_TEMP`. `run` points the two automatic paths at it through the documented
  overrides, `PHASE_LOOP_SANDBOX_STAGING_DIR` and `XDG_CACHE_HOME`, sets `TMPDIR` to a
  private directory on it, and launches its command as a oneshot unit of the user
  manager. A loop device is a whole block device, so the capped parent receives real
  `io.max` rows for it. `TMPDIR` is needed because the strict conformance suite runs under
  the test suite's host isolation, which replaces both overrides with paths below pytest's
  `tmp_path`; those follow the temporary directory, which on some runners is on a device
  that cannot carry `io.max`.
- `teardown` runs on every outcome. It stops leftover seat and gate units, unmounts without
  forcing, and detaches only the device whose backing file is the job's own image. A busy or
  leaked scratch fails the job before the build.

The verifier's GitHub releases API reads are authenticated with the job's read-only token
(`GITHUB_TOKEN`, `contents: read`): unauthenticated reads from shared runner addresses hit the
per-address rate limit. The gate passes the token only to the verifier's unit, by name
(`run --pass-env GITHUB_TOKEN`), so it never appears in a command line or in the evidence. The
verifier sends it only to `api.github.com`, never with the asset download, and not to the
conformance run.

Nothing in this changes how the runtime decides readiness or enforces caps, and strict
conformance stays strict: `--release` still runs the suite with strict mode set by the
verifier itself and accepts only the report that run wrote.

`phase-loop-runtime/scripts/seat_caps_readiness_report.py` reports the five readiness checks
separately, with check 5 split into the caps record and the device plan. The gate captures it
in the step's own environment first, again after a failed delegation or provision, inside the
user manager before the scratch overrides apply (the baseline), and with them. It is a
diagnostic and always exits 0, except in assert mode (`--expect-device MAJ:MIN`), which the
gate uses to require that both automatic paths and the temporary directory are on the
provisioned device and that the child scratch is not the degraded fallback. A record failure
is reported as a record failure, never retried with the defaults. The gate then runs
`phase-loop-runtime/tests/test_seat_caps_scratch_binding.py` inside the user manager, which
makes the same check from inside a test session, where the strict suite resolves its paths.

The hosted `seat-caps-gate.yml` workflow also sets `PHASE_LOOP_SEAT_CAPS_PROBE=1` and
runs the live enforcement and seat-slice lifecycle tests through `ci/seat-caps-host.sh run`
after scratch provisioning and before teardown.
It skips everywhere else. On the ephemeral gate manager, teardown stops the gate launcher,
reaps dead owners and then bulk-stops any remaining seat units before unmounting scratch.

The `seat-caps-gate.yml` probe runs the same gate on six shards and adds
`phase-loop-runtime/scripts/seat_caps_loop_validation.py`, which performs real direct I/O on
the scratch device through the production capped launch path. It requires each measured
transfer to stay within 1.25 times its bandwidth cap, by dd's own timing after a warm-up, and
the parent's `io.stat` to account for it. An uncapped control slower than twice the cap makes
the result inconclusive, which fails. The claim is narrow: on the observed runners, the I/O
bandwidth caps bind and are accounted at the provisioned loop device for the capped launch
path. The loop backing file can still be cached by the host. Memory, CPU and pids continue to
rest on the child's readback attestation and the conformance obligations. Evidence from both
workflows is uploaded as a `seat-caps-evidence-*` artifact on every outcome.
