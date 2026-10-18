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
`ad7937169e4e5578da525251e796a796224df075` is integrated by a provenance-preserving cherry-pick, including both C6 copies,
the pending-release notice and foundational conformance document.

## Caller boundary

Inject full generated protobuf bindings from that revision and an authenticated
`grpc.aio` OpenShell stub. The module neither creates a channel nor supplies TLS,
issuer pinning, credentials, retry interceptors, or generated bindings. The stub
must have retries disabled, must cooperate with cancellation, and must never log
payloads. The compact descriptor and in-process server are test fixtures. Tests also run
against full generated bindings and actual `grpc.aio` calls over a private Unix
socket. This qualifies that local SDK/channel combination, not the Rust server,
authentication, or a deployed channel.

A `LeaseSession` binds one explicit workspace, owner, and lease. Only the server's
authenticated enrollment establishes ownership; owner text is never authority.
CREATE metadata workspace, STATUS lease identity, and immutable UUID observations
are checked. Pass `expected_generation` when recovering a journaled UUID. An
unbound recovery session learns its UUID from the authenticated observation, not
from a name supplied by task output. LIST is one all-or-error RPC: server-side
pagination must be complete. No partial results or failed inventory become empty.
STATUS and the complete LIST inventory are validated before binding identity.
An accepted `reservation:<lease>` can never transition to a UUID: the pinned
server creates lease rows with `MustCreate`, and unseen fences have no create.
`create_settled`, fence, claim, destruction and barrier observations are monotonic.

Allocate and fsync a new lease before using `fresh=True`. Attempt bits are set
before scheduling CREATE/EXEC and are not cleared on cancellation, refusal,
transport failure, or malformed responses. They are local duplicate protection,
not durable fencing. A new session defaults to recovery mode: STATUS/KILL/LIST
are available, CREATE/EXEC are prohibited. Never recover by passing `fresh=True`.
The unregistered `openshell_journal` adapter supplies durable dispatch recording
and a bridge to the existing reaper; it is not a complete backend.

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
- **R12-L1:** any STATUS `TransportError` permanently prevents EXEC through this
  session, including remote refusals, transient UNAVAILABLE, RPC/local deadlines,
  pre-cancelled bounds and local invalid bounds before dispatch. Later valid ready
  observations cannot clear this poison. Do not STATUS a fresh lease before CREATE:
  the pinned server refuses an unreserved lease, poisoning any subsequent EXEC even
  if CREATE later succeeds. After a polling failure, retain the cleanup obligation,
  KILL this lease and allocate a new durably journaled lease for new work. Outer-task
  `CancelledError` propagates without poisoning STATUS, unlike a bound cancellation
  or deadline. A malformed fenced response also records local kill intent.
- **R12-L2:** a failed current-lease LIST identity bind also permanently poisons
  EXEC, without changing the accepted identity. This does not widen poison to every
  LIST RPC or inventory-validation failure. Safe STATUS/KILL recovery remains
  available after either poison; poison itself is not proof of K2.
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
credential payloads are not included in their message or formatted traceback.
**R12-L3 remains:** `from None` suppresses formatted context, but `__context__`
still holds the raw RPC exception, including remote details. Log only the typed
code/uncertainty; do not walk or serialize raw exception chains. Tests retain this
limit explicitly, including actual `AioRpcError` instances. `DEADLINE_EXCEEDED` maps to
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

The r10 L3–L6 integration obligations remain open:

- **L3 barrier coupling:** the client requires destruction evidence for any bound
  UUID. The pinned server currently settles creates only with `Some(id)`; its
  underlying barrier also permits settled `generation=None`. A future terminal
  reconciliation path using `None` requires revisiting this client rule against
  that server change. No such reconciliation is implemented here.
- **L4 channel bounds:** the output cap bounds accumulation, not decoding of each
  message. Per-message buffering is bounded by the injected channel's receive
  limit, which must be explicitly qualified/configured by the integration.
- **L5 separate bounds:** this client conservatively shares one bound across
  dispatch, the RPC deadline and stream collection. The server documents the EXEC
  field as a dispatch bound and has a 15-second relay-open wait. Splitting dispatch
  and collection bounds remains backend integration work.
- **L6 worker inputs:** generated and compact fixtures now include `environment`,
  `workdir`, `execution_timeout` and `no_login_shell`; the local wire test checks
  their unchanged pass-through. The future worker/backend must refuse
  nonempty environment and absent execution timeout, define runtime-owned workdir
  and login-shell behavior, and qualify fixed ends. These checks are not supplied
  by this transport increment.

Tests exercise client handling of applicable falsifiers 1–5 and 7–10; falsifier
6 is explicitly unsupported. They do not demonstrate a physical launch cutoff,
VMM destruction, service restart persistence, direct-operation bypass prevention,
or real authenticated ownership. The private recovery report maps each test.
Still required: authenticated production-channel qualification, cancellation
backend/worker integration, fixed ends and endpoint
bounds, transfer/publication/collection/renewal, terminal remote-create and orphan
reconciliation, authority/store-loss detection, independent bounded reaping,
enrollment resource-class completeness, issuer rotation, memory-only credential
delivery and logging checks, C5 isolation, importer/native completion evidence,
PostgreSQL multi-replica qualification, physical falsifiers and live acceptance.
Source tests authorize no activation, deployment, or live workload.


## Reproduce the bounded generated-binding qualification

Use a Python 3.13.15 interpreter with the repository test dependencies installed.
The r13 run used grpcio-tools **1.84.0**, grpcio **1.84.0**, protobuf **7.36.2**,
setuptools **84.0.0** and typing-extensions **4.16.0**, installed only in scratch.
The generator distribution requires protobuf `>=7.35.1,<8.0.0` and grpcio
`>=1.84.0`; its generated Python code validates protobuf 7.35.1 compatibility at
import. These versions were resolved and imported successfully, not inferred from
a proposed version number. They are qualification dependencies, not new runtime
package requirements.

From `phase-loop-runtime`, set `PYTHON` to that interpreter and `SERVER` to the
read-only pinned OpenShell checkout. This recipe writes only to a new private
scratch directory. Keep it and its hash manifests with the qualification evidence;
do not commit generated modules. No shared cache copy is needed.

```sh
set -eu
: "${PYTHON:?set the test interpreter}" "${SERVER:?set the pinned server checkout}"
test "$(git -C "$SERVER" rev-parse HEAD)" = d16558327be26766f57882b081c7de2333505909
test -z "$(git -C "$SERVER" status --porcelain)"
QUAL_SCRATCH=$(mktemp -d /tmp/openshell-sdk-XXXXXXXX)
mkdir "$QUAL_SCRATCH/generated"
uv pip install --no-cache --link-mode=copy --python "$PYTHON" \
  --target "$QUAL_SCRATCH/deps" grpcio-tools==1.84.0 grpcio==1.84.0 \
  protobuf==7.36.2 setuptools==84.0.0 typing-extensions==4.16.0
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$QUAL_SCRATCH/deps:$PWD/src:$PWD/tests"
"$PYTHON" -m grpc_tools.protoc --version
"$PYTHON" -m grpc_tools.protoc -I "$SERVER/proto" \
  --python_out="$QUAL_SCRATCH/generated" \
  --grpc_python_out="$QUAL_SCRATCH/generated" \
  --descriptor_set_out="$QUAL_SCRATCH/generated/openshell.desc" --include_imports \
  "$SERVER"/proto/*.proto
(cd "$SERVER/proto" && sha256sum *.proto) > "$QUAL_SCRATCH/proto.sha256"
(cd "$QUAL_SCRATCH/generated" && sha256sum *.py *.desc) > "$QUAL_SCRATCH/generated.sha256"
export OPENSHELL_GENERATED_DIR="$QUAL_SCRATCH/generated"
"$PYTHON" -m pytest -q -p no:cacheprovider \
  tests/test_openshell_transport.py tests/test_openshell_transport_grpc.py
```

With the environment variable set, missing or incompatible generated modules fail
rather than silently falling back. Without it, generated cases explicitly skip;
that run is not SDK qualification. All original 68 cases and the 15 r12 probes
run with both binding variants. The r12 LIST probe now asserts permanent refusal
and successful cleanup. Public map/message fixtures use the actual field shapes;
stream parameters instantiate messages after choosing the binding variant.
The descriptor test recursively compares every represented field's number,
cardinality and type, with explicit int32 substitutes for two compact enums.

The local server registers the generated OpenShell servicer and uses its generated
stub, `grpc.enable_retries=0`, and no service config. Tests assert both full RPC
paths, complete serialized requests (including worker fields), real status-code
mapping, and exactly one handler entry for each control operation and EXEC under
RPC deadline, bound cancellation and outer-task cancellation. Handler-entry and
cancellation events synchronize the tests. STATUS-before-CREATE models the pinned
server's FAILED_PRECONDITION and verifies cleanup after the resulting poison.
Synthetic payloads are used throughout. There is no external endpoint, TLS,
provider, VM, production retry configuration, or physical cancellation evidence.
The complete generated SDK cannot substitute for actual-server qualification or
physical falsifiers. The remaining gates above stay open; offload stays disabled.


## Durable journal adapter (bounded r15 increment)

`JournalSession` attaches once to a `placement_lease.Lease`. Only `open_lease`
creates an in-memory fresh capability. `recover_lease` acquires the existing
nonblocking exclusive flock and always creates an observation/cancellation-only
handle, including for legacy entries without markers. A second attachment,
concurrent recovery, an unlocked handle or an inherited handle in a forked
process cannot grant dispatch. Recovery checks the locked descriptor's device,
inode and positive link count against the path without following symlinks before
returning a handle. Inherited or released handles cannot clear an entry. Inherited
transport attachment, dispatch and reference recording refuse before taking the
mutex; journal updates are no-ops. Explicit child `clear` or `abandon` closes only
its descriptor, without explicitly unlocking the shared flock or waiting on an
inherited mutex. No automatic child descriptor cleanup or age-based stale-writer
takeover is supplied.

`create_sent_at` and `execute_sent_at` are conservative attempt markers, fsynced
before calling the transport. They are never proof that a network send occurred.
An error or crash after a marker cannot authorize another send. Reference writes
from validated CREATE/STATUS are also fsynced. A failed sync fences the live
handle; a truncated/malformed entry remains an obligation, never a fresh lease.
No request body, credential or result is journaled. Legacy fields are accepted;
unknown fields and malformed markers are retained without contacting a backend.

`ReaperAdapter` is injected with the same owner, workspace, stub and running aio
loop. Run the synchronous reaper outside that loop. Its optional `kill_journaled`
hook receives the locked entry's snapshot so KILL binds the recorded generation.
It never writes through a borrowed file descriptor: a late RPC completion cannot
write after the reaper releases the lock. KILL requires barrier plus STATUS;
complete LIST must also omit the lease before the existing reaper clears it.
Pending, timeout, invalid identity, failed LIST, or continued presence retains the
entry. `JournalSession.kill` abandons on failure, retaining the existing
`sandbox_placement_release_unconfirmed` notice semantics. The local gRPC model
now excludes a lease from LIST on barrier confirmation, not merely fencing.

This adapter has no enrollment, channel creation, registration, driver activation
or new settings. Callers supply resolved bounds/caps from packaged settings with
existing user/repository overrides. End-to-end bounded reaping with an actual
server remains unqualified. No full ExecutingBackend, physical barrier,
credential path or worker refusal qualification follows from these tests.

R14 N1 (recorded digests not checked by the generation recipe), N2 (version-pinned
but not wheel-hash-pinned dependencies), and N3 (future production channel factory
retries-off/receive-limit qualification) remain open. The r13 generated scratch
is reused read-only for tests; no new generator or supply-chain qualification is
claimed. R12-L3 raw exception chains and r10 L3–L6 above remain open.

R16 L-a–d remain future work: untouched inherited descriptors retain locks until
closed; reaper hook routing uses duck typing; driver reference writes can bypass
the transport no-replacement guard; synchronous fsync/loop-thread contention,
same-loop reaper calls, CLI loop injection and reaper directory fsync remain
unqualified. Backend wiring must address these boundaries before use.

R18 L-a also covers descriptor reuse: workers must exec or close inherited lease
descriptors instead of calling Lease methods after closing/reusing fd numbers.
R18 L-e–g remain with the wiring owner: do not call `clear` and `abandon`
concurrently on the same handle; clear recovered entries only through `reap` or
an equivalent KILL/STATUS/LIST-absence barrier; the reaper lacks recovery's
post-flock identity check and can issue a redundant kill after an open/clear race.
