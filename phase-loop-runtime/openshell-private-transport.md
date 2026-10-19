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
positive protobuf Duration from the caller's `OperationBound`. Control RPCs use
that deadline; EXEC dispatch uses it in the request and a separate finite
`stream_bound` for the aio RPC deadline and local collector lifetime. Local
cancellation/deadline cancels the pending call. No RPC retry or fallback is
performed. A stream has explicit combined stdout/stderr byte and message caps. It requires one
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
- **L5 separate bounds:** the local client now separates dispatch and collection
  as described below. The server documents the EXEC field as a dispatch bound and
  has a 15-second relay-open wait. Actual-server timing, fixed-end enforcement and
  backend receipt mapping remain integration obligations.
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

The explicit CI-ready entrypoint uses the frozen
[`scripts/openshell-sdk-manifest.json`](scripts/openshell-sdk-manifest.json).
It verifies all 11 proto inputs, bundled generator inputs, 23 generated outputs,
and five approved wheel artifacts. Wheel pins were checked against PyPI release
metadata and freshly downloaded content; installation uses `--require-hashes`,
`--no-index` and only those wheels. Versions have one authority in the manifest.

Use the manifest's interpreter/platform with repository test dependencies already
installed, plus `git`, `uv` and `openssl`, and PyPI content reachability for the
pinned wheel downloads. From a clean committed `phase-loop-runtime` checkout:

Use a dedicated clean qualification worktree: the whole `phase-loop-runtime` tree
must contain no changed, untracked or ignored files, including root modules,
pytest configuration, in-tree virtual environments and `__pycache__` directories
and standalone sourceless `.pyc` modules. Global Git ignores and `info/exclude`
do not exempt files. The recipe checks at startup, after generation before pytest,
and at completion; it refuses without deleting files. Keep local environments and
qualification output outside the runtime tree; use an external environment. The
recipe never deletes user files to make a checkout qualify.

```sh
"$PYTHON" -I -B scripts/qualify_openshell_sdk.py \
  --server "$SERVER" --work "$NEW_PRIVATE_QUALIFICATION_DIRECTORY"
```

The work directory must not exist. The command reads the immutable server commit's
Git objects, so a separate evolving server checkout need not be reset or changed.
It writes only its new private directory, installs dependencies into that directory,
and disables bytecode writes and pytest result caches. Allow about 100 MiB. Missing prerequisites,
input/output hash mismatches, skipped/xfail/xpass tests, or a failed narrow test run refuse
qualification. `qualification-receipt.json` is written only after success, recording
the actual clean harness commit/tree, interpreter and uv versions, computed input,
installed payload and output hashes, test counts/outcome, bounds and completion time.
Generator and pytest startup exclude the caller's working directory and Python
environment injection; pytest loads only explicitly selected external plugins.
Pytest uses the tracked `pyproject.toml` explicitly, fixes its root to the runtime
tree and limits conftest discovery to `tests`. Importlib mode avoids adding test
package ancestors to `sys.path`; runtime-root and ancestor config/conftest files
are not discovered. The existing test helpers remain on explicit import paths.
Installed payload bytes are checked against the verified wheels immediately after
installation and again before pytest. The complete installed file set and bytes
are also captured after installation and must match before pytest; only named
installer metadata and the known protoc launcher may supplement wheel payloads.
Unexpected entries and symlinks refuse qualification. The receipt includes both
wheel-derived payload hashes and the complete installed-tree hashes.
Each generator/test child uses a separate freshly allocated bytecode-cache prefix,
so existing source caches and predictable work-directory caches are not reused. Git, uv, protoc, download and pytest bounds are centralized in the
recipe's `TIMEOUTS` configuration. The interpreter and its installed test dependencies
remain trusted caller prerequisites, along with PATH tools and committed source.
Git index flags (including skip-worktree and assume-unchanged), configuration and
repository metadata are trusted; status checks do not defend against their manipulation.
This is not a fully hermetic environment or protection against concurrent mutation
of the checkout, private work directory or trusted interpreter. The ignored-file
refusal covers the entire runtime tree at all three checkpoints. Interpreter/venv
site files (including `.pth` files) and PATH tools remain trusted; this does not
protect against arbitrary concurrent same-user modification.
The narrow run includes transport, local gRPC and subprocess TLS channel tests. The opt-in
`_openshell_qualification` pytest plugin also rejects missing/mismatched SDK bytes,
extra entries and symlinked SDK files/directories before collection;
ordinary optional developer runs retain their skip behavior.
Main CI workflow integration remains outstanding; ordinary CI is not qualification.

These pins support the **existing reviewed wire** only. They do not supply bindings
for new server RPCs. After new wire review, regenerate and review the input/output
manifest together. Byte hash enforcement establishes identity, not cross-platform
reproducibility or live proof; a fresh generation matching retained r13 output is
bounded evidence for this interpreter/generator/platform only.

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
loop. Run the synchronous reaper outside that loop. Its explicitly opted-in
`JournalReapingBackend.kill_journaled` hook receives the locked entry's snapshot
so KILL binds the recorded generation.
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

R14 N1 (recorded digests not checked by the generation recipe) and N2 (version-pinned
but not wheel-hash-pinned dependencies) remain open. N3 has an implementation in
the unregistered factory below, but shutdown verification remains incomplete.
Arbitrary injected stubs retain N3. The r13 generated scratch
is reused read-only for tests; no new generator or supply-chain qualification is
claimed. R12-L3 raw exception chains and r10 L3–L6 above remain open.

## Unregistered lifecycle connection (r21)

`openshell_journal.OpenShellBackend` exposes only synchronous `kill(lease_id,
bound)` and `list_owned(owner_id, bound)`, inheriting the journal-aware reaper
bridge. It is deliberately not an `ExecutingBackend` and cannot be registered as
one. It has no CREATE, EXEC, admission, staging, collection, credential or channel
factory methods. There is no CLI construction path or launch-site import; the
nonlocal execution flag remains false.

Direct `kill` exclusively recovers an existing journal, binds its immutable
reference, and calls KILL plus validated STATUS through `ReaperAdapter`. Only the
synchronous owner writes the returned reference with `record_transport_ref` and
records the kill. Success and failure both abandon the retained entry; direct
kill never clears it. `reap` must independently confirm KILL/STATUS and complete
LIST absence before removal. A held lease cannot be recovered; its live owner
continues to use `JournalSession`. No cleanup call can grant CREATE/EXEC replay.

Journal-aware reaping requires nominal `JournalReapingBackend` inheritance;
an unrelated method named `kill_journaled` does not opt a backend in. Reaper
reference writes also use `record_transport_ref`, never the driver's
`record_sandbox_ref`. Legacy driver backends retain that path; nominal live-lease
backends use immutable commit confirmation as described below.

The bridge rejects any calling thread with a running event loop, stopped/closed
injected loops, and fork-inherited bridge instances before waiting. Reaping checks
this on its caller thread before starting workers, so the worker wrapper cannot
hide a same-loop call. An injected loop must remain running on another thread
throughout use. Timed-out RPCs are cancelled; even a cancellation-resistant late
completion has no journal handle and cannot write after ownership is released.

`clear`, `abandon` and `_unlock` serialize ownership changes using the lease
mutex. Fork guards remain before mutex acquisition, and inherited cleanup closes
only its descriptor without `LOCK_UN`. Reaping now checks descriptor/path device,
inode and link count after flock, for final and pending entries alike, before any
remote cleanup or pending unlink. Recovery's existing check is retained.

R16/R18 L-b, L-c and L-e–g are addressed for this lifecycle-only path. L-f is a
caller constraint: arbitrary direct use of `Lease.clear` on recovered handles is
still not a barrier API. L-d is narrowed by loop misuse rejection, not closed:
synchronous journal I/O, event-loop contention, dedicated CLI loop ownership and
reaper directory fsync after unlink remain obligations. No new timeout, worker
cap or operational setting is introduced; supplied `OperationBound` and existing
reaper settings defaults/overrides remain authoritative.

R18 L-a remains: inherited descriptors retain locks until closed, and closing and
reusing their numbers before calling Lease methods can close an unrelated fd.
Workers must exec or close inherited descriptors without subsequently reusing the
old Lease handle. Production channel retries-off/receive limits, generated
artifact and wheel digest enforcement, raw exception context, worker inputs and
fixed ends, authenticated enrollment/rotation, stage/collect/auth/one-shot channel
construction and native completion are still required before a full executing
backend/CLI can be implemented and qualified. Actual-server CREATE/EXEC remains
closed. Local model and SDK tests never substitute for live acceptance or physical
destruction/restart/bypass falsifiers. No earlier qualification obligation is waived.

## Nominal live-lease driver binding (r37)

`placement_lease.LiveLeaseBackend` is an explicit opt-in contract. Before admission,
the driver calls `bind_live_lease(lease)` once on that rung's original, locked Lease.
The hook must perform no remote effects and return the adapter attached to that
handle. For OpenShell this is one `JournalSession`, retained through admission,
commit, execution and live kill; live kill must not recover a second handle.
An unrelated duck-typed hook is ignored. This adds no executing backend or registry
entry, and existing non-opt-in backends retain their previous behavior.

CREATE records its accepted generation through that session. At commit, the driver
uses `confirm_commit_ref(adapter, sandbox_ref)` to compare and fsync that generation,
never install the commit result's reference. Missing CREATE, a substituted reference
or adapter, a fenced/released handle, or a recovered handle refuses confirmation.
Session construction failure consumes the attachment and fences the handle. A late
commit cannot write through an abandoned handle after recovery; recovered sessions
cannot dispatch CREATE or EXEC. Cancellation suppresses acceptance, without changing
the server's permission for previously claimed work to start while cancel is pending.

This closes only the live binding and immutable driver commit prerequisite. Tests
use synthetic backends and compact/generated protocol fixtures. A real backend must
still integrate source publication, one-shot worker sealing, distinct dispatch and
collection bounds, result quarantine and same-session live cleanup. KILL plus STATUS
destruction/settled-obligation barrier and complete LIST absence remain necessary
before journal removal. The execution flag and production CREATE/EXEC gate remain
closed; all carried qualification and synchronous I/O limitations above remain.


## One-shot dispatch and local stream collection (r44)

The finite-run interface is `JournalSession.dispatch(request, dispatch_bound,
stream_bound=..., output_cap_bytes=..., message_cap=...) -> ExecStream`.
Use the original attached live session. It fsyncs the existing EXEC attempt marker
before constructing the one and only RPC. `stream_bound=None` is unsupported and
refused before the marker. Other invalid bounds/caps refuse without an RPC; a
journaled attempt stays consumed. Bounds and caps come from the caller's resolved
settings/finite workload end; no operational defaults or settings loader are added.

`LeaseSession.dispatch` returns after the nonblocking grpc.aio call constructor,
without waiting for headers, first output or EOF. This proves only local dispatch,
not server acceptance or readiness. The request's bound is the dispatch budget;
the RPC deadline is the finite overall stream budget, measured from dispatch and
never renewed by polling. The supplied stub must have a nonblocking constructor.
A future backend must map dispatch uncertainty conservatively, retain the handle,
and bridge its dedicated loop to driver `wait`; no driver contract changes or
backend registration are supplied here.

`await handle.wait(wait_s)` returns `None` for a poll with no terminal result,
or `StreamResult` only after one exit and clean EOF. It never dispatches, reads a
second stream, recovers a lease, resumes collection, or replays credentials. All
messages count, including empty output and the exit. Output accumulation is capped
across stdout/stderr; channel receive/decode bounds remain the channel owner's
obligation. Malformed/post-exit messages, overflow and stream loss permanently
fail this collector. Raw exit is not native completion or artifact acceptance.

Cancellation/deadline is checked before returning even a completed result. Cancelling
a waiter or calling `handle.cancel()` discards the collector; poll expiry alone
does not cancel it. The JournalSession handle also refuses after lease fencing or
ownership release. Collection callbacks never write the journal; late events cannot
alter recovered ownership or become accepted output. The loop must stay alive for
the finite collection lifetime, and the eventual backend must cancel the handle
when releasing ownership. A stalled stream otherwise remains bounded by its fixed
end. This does not solve synchronous fsync/loop contention limits.

Live KILL uses `JournalSession.kill` on that same attachment and stops local
collection first. Local stream cancellation is not a destruction barrier. Claimed
EXEC may still start remotely while KILL is pending; cancelled output is refused.
Only exact destruction plus settled obligations, validated through KILL/STATUS,
and complete-LIST absence permit journal removal. Failed/pending KILL retains the
journal. Never route live cleanup through recovery of the already held lease.

The existing async `execute(request, bound, output_cap_bytes=...)` remains a
whole-stream convenience wrapper using the same bound for both phases. Its finite
message cap is derived as output-cap + one terminal event (so excessive empty
chunks now refuse); integrations needing independent caps use `dispatch`.
If its collection poll expires without a result, the wrapper cancels the stream
and raises an uncertain operation timeout; the journal wrapper also fences the
original lease. It never returns `None` or authorizes redispatch. Caller-task
cancellation still propagates. This does not change split `wait` poll semantics.
`transfer`, `commit`, `collect` and `renew` remain unsupported. Neither execution
gate changes. Source publication, worker sealing, native witness/quarantine,
actual-server expiry, same-session backend routing and all live/physical/channel
qualification remain owed; this increment is only the local stream boundary.

## Finite implementation driver integration (r54, model-only)

`openshell_backend.OpenShellBackend` now connects `place` / `run_placed` to the
original `JournalSession`, an injected source-stage adapter and the existing
one-shot worker/artifact boundary. It is single-use and **unregistered**. Its
constructor refuses production use (`production_adapters_unqualified`); tests
must explicitly pass `model_only=True`. This is lifecycle integration, not a
claim of physical `ExecutingBackend` conformance. There is no CLI/entrypoint,
channel import, enrollment, server RPC implementation or activation. Production
CREATE/EXEC and the launch-site flag remain closed.

The driver accepts a distinct `implementation` workload. It is subject to the
same closed gate as `leg`; only `qualification` remains exempt. This narrowly
extends the original C1/C10 workload vocabulary without disguising edits as
qualification. No existing ordinary backend is opted into live binding. The
post-wait cancellation check makes cancellation win a simultaneous result, and
cancellation also wins an already-failed launch. No completion receipt follows
those cancellations. Original C1–C12 semantics otherwise remain in force.

Runtime callers supply a `prepare_source` bundle from an immutable clean commit,
a `Prepared` and `PlacementRequest` with that bundle's digest, resolved caps,
trusted task/test IDs and login snapshot reader, a NEW private quarantine path,
and authenticated stub/bindings on an externally owned dedicated running loop.
The model tests substitute an in-process endpoint, not a channel or actual RPC.
The reviewed channel and SDK qualification line is now merged alongside this model.
The backend does not construct a channel or integrate a stage RPC. Channel lifetime
must surround backend and recovery use.

Injected interfaces, unavailable in production here:

- `StageAdapter.validate_configuration()` refuses unusable runtime configuration;
  async `commit(StageBinding, SourceBundle, OperationBound)` must publish verified
  source under lease-owned cleanup obligations. It returns exactly the same
  workspace, owner, lease, generation and recomputed source digest. This is an
  adapter seam, **not** an assertion that any existing staging RPC implements it.
  The local fixture actually materializes and scans a disposable source tree;
  its worker consumes that staged bundle. It cannot establish server atomic
  publication, cleanup obligations or endpoint lifetime.
- `WorkerAdapter.validate_configuration()`, `create_request()`,
  `exec_request(wire, remaining_end_s)` and `validate_native(identity, envelope,
  Bound)` are trusted runtime hooks. Image digest and native validation come
  from this injected runtime, never returned worker claims. The EXEC mapping
  must preserve stdin, set a positive timeout at or before the remaining end,
  use a runtime-owned absolute workdir/program, no environment and no login shell.
  No real image/isolation/native-attestation adapter is supplied. The model uses
  the existing synthetic provider and its declared content check, with synthetic
  credentials only; its witness and test success remain untrusted claims.

Binding happens once before admission. Admission journal-marks CREATE before
sending it, then polls readiness without a pre-CREATE STATUS. Commit is attempted
once, requires the exact StageBinding type, checks all its fields and confirms the original generation without
replacing it. Late returns after cancellation or lost ownership are discarded.
Seal runs once, binds a fresh nonce to the generation/source/task/image/limits,
and requires a finite subscription token lasting the workload. The backend
refuses indefinite deadlines locally, before lease allocation/CREATE in the driver.
Renew explicitly raises unsupported; it never returns a fabricated success.

EXEC journal-marks once and returns after dispatch. The separate collector uses
the fixed remaining end, byte/message caps, and observes cancellation or lease
ownership loss even without output. `wait` polls that same stream; it never
reconnects, relaunches, reseals or refreshes credentials. Stream loss is terminal.
The bridge observes late task exceptions without logging exception chains. It
bounds cooperative calls but does not qualify synchronous fsync, event-loop stalls
or a noncooperative C extension; production bounded shutdown remains owed.

The identity domains are intentionally different:
`Identity.request_sha256` hashes the worker's canonical credential-free metadata;
C9's `request_sha256` hashes the exact `ExecSpec.request` bytes. After trusted
native validation and `validate_result`, the backend returns a small driver
result containing both digests, the quarantine path/hash, and
`isolated_same_base_retest_and_owner_acceptance`. It does not copy a worker digest
into C9 or use a result echo as native evidence. Quarantine is still untrusted;
there is no owner acceptance, isolated client retest or apply-to-user-tree.
A quarantine created before cancellation wins at the driver's delivery boundary
may remain as untrusted evidence, but earns no completed receipt.

Live KILL uses the same attached session while the journal is held; it never
recovers another handle. KILL plus exact-generation destruction/settled-obligation
STATUS and complete LIST absence are required by the driver before clear. Pending
KILL or continued LIST presence retains the journal and release-unconfirmed
notice. Already-claimed EXEC may start while cancellation is pending; no local
stream cancellation is destruction proof. Recovery remains the separate
`openshell_journal.ReaperAdapter` / cleanup-only `OpenShellBackend` path. Neither
successful work nor a quarantine patch can clear a cleanup obligation.

Capabilities are empty and commit returns only a backend claim: no qualification
receipts are synthesized. Required C5 capabilities therefore refuse before any
effects. Still owed: real authenticated materializer and atomic source publication,
worker/endpoint expiry surviving client loss, exact-generation VM destruction,
C5 descriptor/HOME/build/tmp/network/supervisor isolation, immutable image and
nonce attestation, trusted native completion, same-base client retest, artifact
and SDK/wheel provenance enforcement, auth/enrollment/issuer rotation, credential
logging/zeroization, bounded production channel shutdown, terminal-create/orphan
and store-loss reconciliation, PostgreSQL restart/multi-replica and bypass/physical
falsifiers, contract-floor verification and live acceptance. No local model result
waives these blockers or qualifies the separately active server lane.

## Authenticated channel boundary (r23 recovered in r27, unregistered)

`openshell_channel.authenticated_channel(ChannelConfig(...), generated_service)`
is an async context manager yielding a scoped stub for `LeaseSession` or the
cleanup bridge. Nothing constructs it at a launch site or registers a backend.
It implements only the pinned SDK's direct HTTPS plus OIDC bearer pattern
(`crates/openshell-sdk/src/{transport,auth}.rs`). It omits the SDK's anonymous,
plaintext, insecure-verification and edge-tunnel branches. No auth policy is
inferred from owner text. The Rust cancellation ingress authorizes the workspace,
binds the authenticated principal to the owner and requires existing enrollment;
ENROLL separately requires admin access and an empty dedicated workspace. This
factory never enrolls, acquires tokens, decodes claims or proves enrollment.
Enrollment is permanent: changing the authenticated principal cannot adopt an
old owner by reusing its text identifier. Issuer trust and rotation policy remain
the caller/server's responsibility, not a consequence of TLS readiness.

Supply explicit CA PEM bytes and a bearer token in memory, a canonical HTTPS
endpoint, workspace and the current `placement_lease.owner_id()`. Both secrets
are excluded from config repr. Empty/malformed trust, credentials, endpoint,
scope or limits refuse before channel construction. No system-root fallback,
TLS name override, arbitrary options, interceptor or ambient HTTP proxy is used.
The endpoint hostname is the TLS identity. TLS readiness is not bearer acceptance:
only server RPC authorization establishes principal/workspace/enrollment validity.
The scoped stub checks current local owner, request workspace/owner, PID, running
loop and finite positive RPC timeout before dispatch. It does not inspect worker
payloads, establish membership, or substitute for server authorization.

The immutable config has no operational defaults. Resolve settings once through
`load_placement_driver_settings`, preserving packaged defaults, user/repository
overrides, environment aliases and `review_base=True` for trusted-base reviews;
pass the applicable remaining connection allowance explicitly. Do not copy the
SDK's connect/keepalive constants. Harness currently has **no authoritative
OpenShell receive-limit, endpoint, CA or token setting**. These remain required
injected inputs; this increment adds no settings key, credential discovery or
default trust policy. The receive limit is a positive signed-32-bit byte count,
not an output cap, and must be budgeted by the eventual caller. Generated modules
are still explicitly supplied and their provenance remains the caller's obligation.

The factory implements R14 N3's required options: retries are disabled,
resolver service config is disabled, no retry service config is supplied, and a
finite per-message receive limit is always passed. Tests assert the exact option
set, refuse option injection, exercise one handler entry on RPC failures even
with an adversarial retry policy, and require RESOURCE_EXHAUSTED for an oversized
message. Mutating retries on makes the policy test observe repeated calls;
mutating the receive limit to unlimited defeats the oversized-message test.
Synthetic loopback TLS tests
require the supplied CA, matching DNS name and bearer delivery; wrong roots,
wrong hostname and plaintext cannot yield a stub. A rejected bearer fails the
RPC even after TLS readiness. These do not qualify a deployed
channel, real issuer or the Rust server. Existing arbitrary injected stubs retain
their caller-owned channel obligations.

Construction and use belong to one running asyncio loop. Connection readiness is
bounded by the supplied timeout and outer cancellation. Context exit cancels
outstanding RPCs immediately (no graceful drain), closes the channel and refuses
further calls. Keep the loop alive through exit; a synchronous cleanup bridge must
run outside it and finish before exit. This supplies no dedicated CLI loop/thread
manager or end-to-end latency bound under loop starvation. Reconnection uses the
same verified TLS credentials; application RPC retries remain disabled. Credentials
are a fixed snapshot: expiry/rotation requires closing and reconstructing with
explicit new inputs, with no replay or automatic enrollment. Python/gRPC memory
zeroization, token lifetime qualification and logging remain open.

The r27 local runs encountered intermittent stalls inside gRPC 1.84.0's
synthetic TLS server shutdown. The r35 recovery reproduced the stall with zero
grace in both combined and channel-only runs; zero grace is not a fix. A bounded
debugger-launched reproducer captured the main thread waiting inside native
`cygrpc` shutdown. The Python traces stop at `grpc.aio.Server.stop`; these traces
do not establish the native root cause or exclude a production lifecycle defect.
Earlier separate channel and transport/journal passes do not resolve this failure.
Retained timeout traces are not successful qualification. No bounded shutdown
guarantee for that runtime or actual-server readiness follows from these tests.

N1/N2 artifact/wheel verification and R12-L3 raw exception context remain open;
the scoped stub's raw RPC errors still go through `LeaseSession` for typed mapping.
The execution/staging/collection, immutable commit-reference, fixed-end, rotation,
reaper, physical and live qualification obligations above are unchanged. Pending
cancellation still permits previously claimed execution; confirmation still needs
exact destruction and settled obligations. Production CREATE/EXEC and
`_NONLOCAL_EXECUTION_DRIVER` remain closed.
