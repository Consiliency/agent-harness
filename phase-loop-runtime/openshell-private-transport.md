# Disabled OpenShell private transport

`src/phase_loop_runtime/openshell_transport.py` is a private protocol client,
not an `ExecutingBackend`. Nothing registers or imports it at a launch site.
The review execution flag remains false. No settings, endpoint, authentication,
deployment, or resource policy is introduced by importing it.

The wire authority is OpenShell `d16558327be26766f57882b081c7de2333505909`:
`proto/openshell.proto`, private messages and RPCs, and
`crates/openshell-server/README.md` (Private cancellation lease API). Production
CREATE/EXEC remain gated there. The owner-approved destruction barrier is in the
private cancellation amendment r4; Harness foundation
`ad7937169e4e5578da525251e796a796224df075` has been inspected but is **not integrated**
into this driver-based branch. Integrating its two C6 copies and notice wording
remains necessary before a usable backend can ship.

## Caller boundary

Inject full generated protobuf bindings from that revision and an authenticated
`grpc.aio` OpenShell stub. The module neither creates a channel nor supplies TLS,
issuer pinning, credentials, retry interceptors, or generated bindings. The stub
must have retries disabled, must cooperate with cancellation, and must never log
payloads. The test stub and compact protobuf descriptor are modeled fixtures;
they do not qualify a generated client/server connection or authentication.

A `LeaseSession` binds one explicit workspace, owner, and lease. Only the server's
authenticated enrollment establishes ownership; owner text is never authority.
CREATE metadata workspace, STATUS lease identity, and immutable UUID observations
are checked. Pass `expected_generation` when recovering a journaled UUID. An
unbound recovery session learns its UUID from the authenticated observation, not
from a name supplied by task output. LIST is one all-or-error RPC: server-side
pagination must be complete. No partial results or failed inventory become empty.

Allocate and fsync a new lease before using `fresh=True`. Attempt bits are set
before scheduling CREATE/EXEC and are not cleared on cancellation, refusal,
transport failure, or malformed responses. They are local duplicate protection,
not durable fencing. A new session defaults to recovery mode: STATUS/KILL/LIST
are available, CREATE/EXEC are prohibited. Never recover by passing `fresh=True`.
The journal/reaper integration and durable dispatch recording are still owed.

The methods map ENROLL=1, CREATE=2, KILL=3, LIST=4, STATUS=5 to
`ControlCancellationLease`; EXEC uses `ExecCancellationLease` exactly once.
Control and exec messages include explicit workspace, owner, lease, and a
positive protobuf Duration from the caller's `OperationBound`. The aio call has
the same deadline; local cancellation/deadline cancels the pending call. No RPC
retry or fallback is performed. A stream is bounded by that same entire-operation
deadline and a caller-supplied combined stdout/stderr byte cap. It requires one
exit event and EOF; this is a raw protocol exit, not native provider completion
evidence or a verified result. The transport accepts protobuf worker requests;
a future backend must construct them from runtime-owned workloads, never host
argv/environment. This transport does not itself implement the worker boundary.

## Uncertainty

- After a lost CREATE reply call STATUS, never CREATE again. A provisioning UUID
  and `create_settled` do not imply readiness. STATUS never grants replay.
- EXEC uncertainty is final for dispatch. Observe or cancel the same lease; no
  second EXEC, no other rung, no local fallback, no credential replay.
- KILL deadline can precede durable K2. The client stops dispatch locally but
  does not claim a durable remote fence. Safe KILL/STATUS may be called again.
- KILL succeeds only with its positive barrier reply followed, within the same
  remaining bound, by matching STATUS with a fenced, settled, nonpending barrier.
  A known generation also requires positive destruction evidence. LIST absence
  alone never confirms cleanup. The future driver must still require successful
  KILL **and** absence of that lease in complete LIST before releasing its journal entry.
- `create_settled=true` on `reservation:<lease>` means **nothing to settle**, not
  that a generation existed or was destroyed. This supports unseen-lease fences.
- A previously claimed execution may finish while cancellation remains pending.
  Its raw stream result does not confirm cleanup or authorize importing cancelled
  work. Only the destruction barrier establishes the no-start/no-running cutoff.

Protocol failures use input-free typed `TransportError` values; remote prose and
credential payloads are not included. `DEADLINE_EXCEEDED` maps to
`sandbox_placement_operation_timeout`. Other typed protocol errors are internal
to this unregistered client, not additions to the Harness detail-code registry.
`transfer`, `commit`, `collect`, and `renew` raise `UnsupportedCapability` without
dispatch. No physical transfer/commit/collect/renew conformance is claimed.

## Configuration and policy

The caller supplies resolved bounds and output caps; this module introduces no
deployment defaults or config loader. Preserve the packaged driver defaults and
existing user/repository/environment precedence. Resolve one immutable settings
snapshot in the eventual caller and preserve `review_base=True` for committed
trusted-base review controls; do not read working-tree settings implicitly.

CREATE checks the server's inert-supervision restrictions. With network rules,
all paths from pinned `openshell-policy::proxy_baseline_paths()` must already be
explicit: `/usr`, `/lib`, `/etc`, `/app`, `/var/log`, `/proc`, `/dev/urandom`, `/tmp`,
`/dev/null`. Exact spellings are required. The client refuses missing paths and
never adds paths, normalizes spellings, or promotes access modes. This check is
not C5 isolation qualification.

## Remaining qualification

Tests exercise client handling of applicable falsifiers 1–5 and 7–10; falsifier
6 is explicitly unsupported. They do not demonstrate a physical launch cutoff,
VMM destruction, service restart persistence, direct-operation bypass prevention,
or real authenticated ownership. The private recovery report maps each test.
Still required: full generated-binding/channel qualification, cancellation
foundation integration, backend/journal/worker integration, fixed ends and endpoint
bounds, transfer/publication/collection/renewal, terminal remote-create and orphan
reconciliation, authority/store-loss detection, independent bounded reaping,
enrollment resource-class completeness, issuer rotation, memory-only credential
delivery and logging checks, C5 isolation, importer/native completion evidence,
PostgreSQL multi-replica qualification, physical falsifiers and live acceptance.
Source tests authorize no activation, deployment, or live workload.
