# Per-seat resource caps

Local review seats fail closed unless the runtime can put every provider process and SDK
worker for one `seat_key` below one capped cgroup parent. Each process uses a distinct child
scope, so the record limits their combined use. A failed setup or readback reports
`seat_resource_caps_unavailable`; the seat does not run and has no uncapped fallback.

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

It skips when not opted in or when delegation is absent. A release gate needs a pass, not a
skip, on every host that runs review seats. The probe makes no provider call.
