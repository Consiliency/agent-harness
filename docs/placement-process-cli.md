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
including `XDG_CONFIG_HOME`, `XDG_STATE_HOME` and any placement-named variable. The one
placement setting read from the environment, `PHASE_LOOP_PLACEMENT_MAX_INPUT_DEPTH` (see
[Input nesting limit](#input-nesting-limit)), only tightens or loosens the decoders' nesting
safeguard. Each client accepts only its own workloads:

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
- an oversized body, or one nesting arrays or objects deeper than the input nesting limit
  (64 by default; see [Input nesting limit](#input-nesting-limit));
- a schema-invalid object for the verb;
- non-empty stdin for `version`.

Retry the same `request_id` once, and only when the request was schema-valid. Stderr is empty
for every schema-valid outcome. Otherwise it carries one closed line such as
`agent-harness-placement: protocol_failure input_duplicate_key` or
`agent-harness-placement: placement_config_invalid`. Stderr never carries an input value, a
credential, a policy document or an exception chain.

### Input nesting limit

The request decoder (and the `decode_response` client decoder) refuses a JSON body that nests
arrays or objects deeper than a limit, as `input_invalid_json`, before decoding it. The top-level
object counts as depth 1. This is an implementation resource safeguard, not a rule of the frozen
`x-cli.input`, and it makes the outcome the same on every supported interpreter (Python 3.14's
decoder accepts depths that 3.12's raises on). Because the check runs first, a too-deep body
that also breaks another input rule (a duplicate key, an unsafe or non-finite number) reports
`input_invalid_json`.

The limit is 64 unless `PHASE_LOOP_PLACEMENT_MAX_INPUT_DEPTH` is set in the process
environment. The variable is read on every decode.

- **Accepted values.** A plain ASCII base-10 integer from 3 to 256 inclusive: no sign,
  whitespace, underscore, leading zero, decimal point or non-ASCII digit.
  - The minimum, 3, is the deepest schema-valid request or response, so no accepted value
    refuses a valid message or a journaled response on replay.
  - The maximum, 256, keeps input at the limit well inside the interpreter's recursion limit
    on Python 3.12 and 3.14. At 512, input at the limit would itself be refused through
    recursion exhaustion.
- **Invalid values fail closed.** An empty string, or any other value outside the accepted
  form or range, never falls back to 64. While the setting is invalid, every `reserve`,
  `release` and `reap` body that passes the size and UTF-8 checks is refused as
  `input_invalid_json` (exit 70, stdout absent), and so is every response given to
  `decode_response`. No new diagnostic exists for this. `version` reads no JSON and is
  unaffected.
- **Not a protocol field.** The setting adds no message member, diagnostic or exit class. The
  packaged schema and its SHA-256 (`130a894d…83ea`), the vectors and the CLI fixtures are
  unchanged.
- **Client configurations are never limited.** The operator configuration files are parsed
  without a nesting limit and ignore this setting, because their top-level `launch` object is
  uninterpreted and has no depth bound. Nesting too deep for the interpreter to decode or walk
  is still refused as invalid rather than raising.

The deepest real placement inputs in the repository nest far below 64:

- schema-valid process messages nest at most 3 deep;
- the CLI fixture requests nest 2 deep and the fixture client configurations 5;
- the packaged coordinator wire vectors nest at most 8 deep and the policy vectors 7.

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
- **Providers reached only through the link.** A provider can instead name no endpoints and
  set `"reach": "link"`. Model traffic for it goes over the reservation's link to the
  requester's credential proxy, so it adds no endpoint to the sandbox's egress:

  ```json
  "openai": {"reach": "link", "workloads": ["pi-runner"],
             "policy_vectors": ["full-remote-pi-runner", "minimal-without-app"]}
  ```

  Each provider has exactly one of the two shapes: `endpoints` (1 to 16 unique endpoints), or
  `"reach": "link"` with no `endpoints` member. Any other `reach` value, `reach` together with
  `endpoints`, or an empty `endpoints` list refuses at load. Releases before this support
  refuse a configuration that uses `reach`, with `placement_config_invalid`.
- **Targets for `agent-toolkit`.** Targets follow the agent and executor order: OpenShell
  (`ai`), then local, then E2B.
- **Targets for `agent-harness`.** `seat_route` names the single trusted target for each seat
  workload, as decided by the SEATS route (for example `{"leg": "ai"}`). A missing entry
  refuses with `sandbox_placement_workload_unsupported` before any probe.
- **`launch`.** An optional top-level `launch` object is included verbatim in the canonical
  bytes and is not interpreted here. LANEEXEC owns it, and it must carry the sha256 of every
  artifact it names. When present it must be an object; `"launch": null` refuses at load.
- **Unknown members.** Any other unknown member refuses at load.

`config_sha256` is the SHA-256 of the UTF-8 RFC 8785 serialization of the selected client's
effective configuration. That configuration includes:

- the effective headroom thresholds;
- the resolved policy-vector digests;
- the provider mapping, including each provider's shape;
- `launch`;
- `seat_caps_sha256`.

Changing any of them changes `config_sha256`, and `version` reports it. An endpoint
provider keeps its existing canonical form, so a configuration with only endpoint providers
keeps the same `config_sha256` it had before link-only providers were supported.

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

A provider reached only through the link adds its name to `providers` and no rule, so a
request that names only such providers gets the vector's baseline alone. Every packaged
vector's baseline is empty. A request that mixes both shapes gets the endpoint providers'
rules, as before. This follows the existing rule unchanged; the protocol bytes are not
modified.

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

### Durable admission and recovery

An admission is committed in steps, each one durable in the attempt journal before the next
begins:

1. The exact reservation, with its expiry fixed at admission, and its complete cleanup effect
   are journaled. For a bridged reservation, the effect includes the bridge directory it will
   use.
2. A bridged reservation opens its bridge, and the commit is journaled again with the bridge
   handle.
3. The active reservation is published, and then the attempt is settled.

After an interruption between steps, nothing is allocated again:

- **Before the settle bound,** a replay settles `admitted` only from a complete commit. It
  returns the original reservation, expiry and bridge, and publishes the record if
  publication was interrupted. A commit whose bridge was never journaled answers `timeout`.
- **At the bound,** the attempt's complete effect becomes one cleanup entry, and any
  published record of the same reservation is retired, so one owner removes the bridge,
  slot or lease.

Replay may perform one bounded read-only reconciliation; it never creates a target, lease or bridge or recomputes an expiry. Start-up reads each
unsettled attempt again under its lock before settling it, so a record that another process
settled is never overwritten.

The hand-over to cleanup is itself durable and restartable. It is journaled in the attempt,
under stable keys, before any cleanup entry is written, and any later start-up resumes it,
even after the terminal response has been journaled. Every consumer of a reservation's effect
holds that reservation's lock: its active record, its cleanup entry, replay and the hand-over
itself. A consumed cleanup entry is kept as a completion record until the attempt journals the
completion, so an effect that was removed is never handed on again. Once the completion is
journaled, a later start-up removes that record under the same lock, after reading it again
there.

The PLACECLI receipt (`plans/evidence/placement/PLACECLI.md`) pins the CLI boundary: the
protocol schema, its vectors, the CLI fixtures and the producer files. The lifecycle module,
`sandbox_placement.py`, is shared with other placement work and is never pinned by the
receipt, so the recovery behavior described in this section is attested by the hosted test
suite and Gate A on the merge head.

### Deadlines

Each `reserve`, `release` and `reap` call has one deadline, from its `deadline_ms`. Every
blocking step uses what is left of it: the walk, the exposure lookup, the wait for the bridge
to become ready, the reservation lock, bridge teardown, and the kill and owner listing.

- Cancellation also ends a wait for a held lock: the lock is always tried once, and once the
  caller cancels, a contended lock is not waited for.
- Once the caller cancels, cleanup starts no further kill or owner listing. This holds also
  when the signal arrives while the backend is being resolved or the lease is being recovered
  or fenced. A kill that has already started finishes within its bound. Either way the lease
  stays recorded as unconfirmed, and a later release or reap removes it.
- When time runs out, or the caller cancels, after admission, admission is not reported. The
  effects stay journaled, the response is `timeout`, and replay or terminal cleanup takes
  over. This includes a bridge that fails to open after the caller cancelled: no remote
  cleanup starts, and the lease stays owned by the attempt until replay or terminal cleanup
  removes it.
- A release whose lock or cleanup outlasts its deadline answers `cleanup_pending`. The client
  and id are always checked; the echoed reservation is compared only once the reservation
  lock is held. A release whose lock wait ends by deadline or cancellation answers
  `cleanup_pending` with no comparison, and nothing is released.

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

  An effect listed both as a reservation and as a cleanup entry is visited and counted once,
  and `max_items` bounds distinct effects. An uncertain item stays pending, without a
  client-wide or host-wide barrier.
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

The helper relays without blocking. Each direction has a bounded buffer, so a peer that stops
reading stalls only its own direction. An end of stream is passed on once the bytes ahead of
it have drained. Every wait is bounded by the reservation's end, so the helper stops promptly
when it is told to and always at expiry, removing its socket and directory. If the helper's
handle was never journaled, cleanup still finds the helper by the reservation's directory.

Local reservations have `bridge: null` and use the requester-owned proxy in process.

### The openshell launch check

`sandbox_placement.openshell_launch_refusal` is the activation check for the launch service
to call on every OpenShell launch, with the effective configuration loaded for that launch and
the reservation's values. It returns `None` to admit, or one of the existing launch codes. In
the launch service's order, binding before activation:

1. The reservation's `config_sha256` must equal the loaded configuration's, or the launch
   refuses `sandbox_launch_input_mismatch`.
2. For every OpenShell workload, the route must be enabled (`openshell_route_state()`), or
   the launch refuses `sandbox_launch_route_disabled`.
3. A `pi-runner` launch also refuses `sandbox_launch_route_disabled` unless every
   `pi-runner` provider in the configuration is reached only through the link, the remote
   vector's baseline is empty and every declared provider is such a provider.
4. A `pi-runner` launch's recomputed grant must carry no rule and equal the reservation's
   `egress_sha256`, or the launch refuses `launch_input_unbound`.

`openshell_route_state()` returns `enabled` only when the packaged policy status is no longer
`pending_qualification`, the non-local execution driver is on and a production OpenShell
backend is registered. A state it cannot read is `unknown`, which no launch accepts. While the
route is not disabled, `reserve` applies the same `pi-runner` rule on OpenShell targets: a
declared provider that is not reached only through the link refuses
`sandbox_placement_provider_refused`, and a configuration that keeps the route closed refuses
`sandbox_placement_driver_unavailable`.

## Toolkit cutover

agent-toolkit keeps its legacy OpenShell and coordinator client as the L0–L9 differential
oracle. It switches only when all three conditions hold:

1. agent-harness reproduces the L0–L9 evidence;
2. the toolkit fixtures pass unchanged as black-box tests;
3. one end-to-end Pi run on `ai` succeeds through the toolkit shim.

The offline corpus in `phase-loop-runtime/tests/fixtures/placement-cli/` exercises the closed
outcomes only. It is not live evidence.
