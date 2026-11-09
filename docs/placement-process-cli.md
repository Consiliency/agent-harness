# Placement process CLI (`agent-harness-placement`)

`agent-harness-placement` is the process boundary through which agent-harness and agent-toolkit
reserve, release and reap placement capacity. It implements placement process protocol v1, the
frozen artifact `plans/artifacts/v13-PLACECLI-contract-v1.schema.json` with erratum
PLACECLI-v1-errata-1. The package ships that artifact byte for byte as
`phase_loop_runtime/contracts/placement/process-v1.schema.json`. Its SHA-256 is the wire
identity that `version` reports.

The CLI stops at reservation, release, reap and bridge construction. Launching a workload
belongs to the later launch service (v13 LANEEXEC). **Live routes are disabled:**

- no production OpenShell backend is registered;
- `panel_invoker._NONLOCAL_EXECUTION_DRIVER` stays false;
- `contracts/placement/vectors/policies.json` stays `pending_qualification`;
- E2B stays disabled.

Nothing in this release reaches a live coordinator.

## Invocation

```sh
agent-harness-placement --client agent-harness|agent-toolkit reserve|release|reap|version
```

The `--client` flag is required. It alone selects the per-client operator configuration, the
certificate OU and the inventory. No environment variable selects or overrides any of them,
including `XDG_CONFIG_HOME`, `XDG_STATE_HOME` and any placement-named variable. Each client
accepts only its own workloads:

| Client | Workloads | Certificate OU | Rank policy |
| --- | --- | --- | --- |
| `agent-toolkit` | `pi-runner` | `agent-toolkit` | `agent_executor` |
| `agent-harness` | `leg`, `qualification`, `implementation` | `agent-harness` | `seats_single_target` |

A request for the other client's workload is refused with
`sandbox_placement_workload_unsupported` before any effect.

`--help` prints the usage and one line with the caps state: either
`seat resource caps: available` or
`seat resource caps: unavailable (seat_resource_caps_unavailable)`. It exits 0.

## Messages and exit classes

`reserve`, `release` and `reap` read one UTF-8 JSON object on stdin, followed by EOF, of at
most 65536 bytes. `version` requires empty stdin. Each call writes exactly one compact JSON
response line to stdout. The message shapes are the artifact's `$defs`.

| Exit | Meaning |
| --- | --- |
| 0 | Settled: a version response, an admitted reservation, a release, or a complete reap. |
| 10 | Nothing created or held: `at_capacity`, `refused` or `unreachable`; `unknown_reservation` or `rejected`. |
| 20 | An effect may remain: reserve `timeout`, or release or reap `cleanup_pending`. |
| 70 | Internal or protocol failure. Stdout is absent. |

All of the following fail as a protocol failure, exit 70 with stdout absent, and make no
effect:

- duplicate keys, trailing data, invalid UTF-8, or non-finite or unsafe numbers;
- an oversized body;
- a schema-invalid object for the verb;
- non-empty stdin for `version`.

Retry the same `request_id` once, and only when the request was schema-valid. Stderr is empty
for every schema-valid outcome. Otherwise it carries one closed line such as
`agent-harness-placement: protocol_failure input_duplicate_key` or
`agent-harness-placement: placement_config_invalid`. Stderr never carries an input value, a
credential, a policy document or an exception chain.

## Operator configuration

The operator configuration lives under the account's home directory:

- `~/.config/agent-harness/placement/<client>.json`: one client's configuration.
- `~/.config/agent-harness/placement/host.json`: optional host-wide headroom overrides.

Each file must be a regular file owned by the user and not writable by group or others. A
missing client file means no providers and no targets, so every reservation refuses.

```json
{
  "schema": "placement.client-config.v1",
  "client": "agent-toolkit",
  "providers": {
    "anthropic": {"endpoints": [{"host": "api.anthropic.com", "port": 443}],
                  "workloads": ["pi-runner"],
                  "policy_vectors": ["full-remote-pi-runner", "minimal-without-app"]}
  },
  "targets": [
    {"name": "ai", "kind": "openshell", "rank": 0, "transport_id": "ai-openshell",
     "root": "openshell://ai/placement", "probe_receipt_providers": ["anthropic"]},
    {"name": "local", "kind": "local", "rank": 1, "transport_id": "local"},
    {"name": "e2b", "kind": "e2b", "rank": 2, "transport_id": "e2b", "od7_providers": []}
  ]
}
```

- **Providers.** Each entry is an operator allowlist of provider names, never URLs, hostnames
  or model names. Each name maps to its endpoints, the workloads it may serve and the policy
  vectors it may run under.
- **Targets for `agent-toolkit`.** Targets follow the agent and executor order: OpenShell
  (`ai`), then local, then E2B.
- **Targets for `agent-harness`.** `seat_route` names the single trusted target for each seat
  workload, as decided by the SEATS route (for example `{"leg": "ai"}`). A missing entry
  refuses with `sandbox_placement_workload_unsupported` before any probe.
- **`launch`.** An optional top-level `launch` object is included verbatim in the canonical
  bytes and is not interpreted here. LANEEXEC owns it, and it must carry the sha256 of every
  artifact it names.
- **Unknown members.** Any other unknown member refuses at load.

`config_sha256` is the SHA-256 of the UTF-8 RFC 8785 serialization of the selected client's
effective configuration. That configuration includes:

- the effective headroom thresholds;
- the resolved policy-vector digests;
- the provider mapping;
- `launch`;
- `seat_caps_sha256`.

Changing any of them changes `config_sha256`, and `version` reports it.

## Reserve

`reserve` first checks the request, in this order, before any capacity probe, coordinator call
or lease. The first failure refuses:

1. **Caps record.** An unreadable caps record refuses with `sandbox_placement_capability_unmet`.
2. **Workload.** The workload must belong to the selected client.
3. **Providers.** Every declared provider must be allowlisted for the client and the
   workload. Otherwise the request refuses with `sandbox_placement_provider_refused`.

It then walks the targets:

- **`pi-runner`.** The walk tries `ai` by authoritative capacity. It then tries an actually
  reserved local slot, only when every headroom threshold admits. E2B is recorded in the
  trail as disabled. On `ai` the request resolves to `full-remote-pi-runner`; locally it
  resolves to `minimal-without-app`, with `bridge: null`.
- **Seat workloads.** These admit only their single trusted target.

Each target can be refused before it is probed:

- a provider is not permitted by that target's resolved policy vector;
- the target is owned and lacks the generic egress-and-credential probe receipt for every
  declared provider;
- the target is third-party and lacks a current OD-7 clearance for every declared provider.

Each attempt adds a `TrailEntry`. A remote rung stops after admission, before any commit,
seal or execute. Its lease stays recorded in the client's inventory and survives restart.
After admission there is no fallback of route, transport, policy, provider, egress or
deadline.

### Effective egress digest

The effective egress grant is exactly the resolved policy vector's baseline plus the
allowlisted endpoints of every declared provider. It is
`{"providers": [...], "rules": [{"host": ..., "port": ...}]}`, with names and rules sorted
and de-duplicated. `Reservation.egress_sha256` is `sha256:` plus the lowercase hex SHA-256 of
its RFC 8785 serialization. No credential enters the grant.

The admitted launch envelope v2 field `launch.grants.egress_policy_sha256.sha256` is the
**bare 64-hex digest**: the hex digits of `Reservation.egress_sha256` after the `sha256:`
prefix. This follows the LANEEXEC artifact's `x-envelope-construction` rule. Where the
PLACECLI artifact's `x-provider-egress.launch_binding` sentence names the digest spelling,
that sentence is non-normative. The protocol bytes stay at their pin, and a future protocol
version will fold the corrected sentence in.

### Idempotency, replay and barriers

The same `request_id` with the same body returns the original response byte for byte,
including after a lost reply or a restart. The same `request_id` with a different body
refuses with `sandbox_placement_refused` and creates nothing.

A reserve that ends in `timeout` (exit 20) is unsettled. It arms a barrier scoped to
`(client, request_id)`, or to `(client, reservation_id)` once one is known. Every other
reservation, of either client, stays admissible.

A replay of an unsettled attempt follows erratum 1:

1. If the replay is at or past the settle bound (the journaled start plus the request
   deadline plus 300 s), or before the start, or the start is unreadable, it settles
   terminally. The response is `timeout` with `sandbox_placement_end_reached` and exit 20.
   The uncertain effect becomes a cleanup journal entry.
2. Otherwise it runs at most one read-only reconciliation. A held, ready lease settles as
   `admitted`. Nothing held settles as `unreachable` with
   `sandbox_placement_operation_timeout`. An indeterminate result answers `timeout` and
   journals nothing.

Reap never answers for a reserve.

## Release and reap

- **Release.** `release` loads the stored reservation by `reservation_id` from the selected
  client's inventory only, and compares the whole echoed reservation:
  - A client mismatch, or any differing field, returns `rejected`. Nothing is released, no
    flag changes and no barrier is armed.
  - A confirmed release returns `released`.
  - An unconfirmed one returns `cleanup_pending` (exit 20). Only that reservation's barrier is
    armed.
  - A repeated release returns `released` while the tombstone lasts (one day). After that it
    returns `unknown_reservation`.
- **Reap.** `reap` examines only the caller's inventory. It visits eligible entries in order
  of `created_at`, then id, bounded by `max_items` and the deadline. Eligible entries are:
  - cleanup entries;
  - `cleanup_pending` reservations;
  - expired reservations.

  An uncertain item stays pending, without a client-wide or host-wide barrier.
- **Legacy reaper.** `phase-loop placement reap --client CLIENT` runs the same caller-scoped
  service in process. Without `--client` it keeps reaping the legacy lease journal.

## Local headroom and caps readiness

The local thresholds are per-host operator configuration. The published defaults are the
packaged `[placement.local_headroom]` table in
`advisor_board/fixtures/placement-driver.defaults.toml`, which equals the artifact's
`x-local-headroom-defaults`. `host.json` may override any of them, and `version` reports the
effective values.

The defaults are:

- `MemAvailable` is at least max(4 GiB, 10% of `MemTotal`);
- one-minute load per online CPU is below 70%;
- `/proc/pressure/io` `full avg10` is below 10%;
- `/proc/pressure/memory` `some avg10` is below 10%;
- there are fewer than four live sandboxes (host-wide, both clients);
- the observation is no older than five seconds.

Any unknown or stale dimension is `at_capacity`, and so is a missing, unreadable or malformed
PSI file or line.

Caps readiness is checked at reservation time against the landed `seat_resource_caps.v1`
record:

- **Unreadable caps record** (`load_caps()` raises):
  - `reserve` refuses with `sandbox_placement_capability_unmet` (exit 10) for every target and
    workload, with zero effects;
  - `release` and `reap` keep working;
  - `version` still exits 0, reporting `seat_caps_sha256` as the documented sentinel
    `sha256(b"seat_resource_caps_unavailable")` inside `config_sha256`.
- **Readable record, non-null `readiness_code()`.** Only local reservations are refused. Remote
  targets stay available.

Applying caps to a placed workload, and per-path readback, belong to LANEEXEC.

## Credential-proxy boundary and the bridge

The placement service and the sandbox hold no model-provider key, token or refresh token.

A `pi-runner` or `leg` reservation on OpenShell gets one bridge:

- one directory, mode 0700, holding one Unix socket, mode 0600;
- the directory lives under the client's state directory, or under `/run/user/<uid>` when
  that path would be too long;
- it is scoped to that reservation and removed on release.

The socket is a raw byte pipe of the admitted ForwardTcp stream. The requester's credential
proxy (for agent-toolkit, `cred-proxy.mjs`) connects to it and keeps link framing, relay and
credentials. A helper serves the socket for the reservation's lifetime. It is this package's
own module, launched through `seat_uid.trusted_module_argv`, and it opens no TCP listener.

Local reservations have `bridge: null` and use the requester-owned proxy in process.

## Toolkit cutover

agent-toolkit keeps its legacy OpenShell and coordinator client as the L0–L9 differential
oracle. It switches only when all three conditions hold:

1. agent-harness reproduces the L0–L9 evidence;
2. the toolkit fixtures pass unchanged as black-box tests;
3. one end-to-end Pi run on `ai` succeeds through the toolkit shim.

The offline corpus in `phase-loop-runtime/tests/fixtures/placement-cli/` exercises the closed
outcomes only. It is not live evidence.
