# CLAUDE SDK worker contract v1

Normative frozen input to EC-CLAUDE-3 and IF-0-CLAUDE-3. EC-CLAUDE-5 uses the same worker
contract for its capture twin. G1 ratifies this contract and the captured launch fixture; GL-2
requires its proof. This document authorizes no activation. Only generic design obligations and
controls belong here. OD-10 keeps case-specific security evidence, raw output and findings in
operator-private storage.

## Process contract

The owned host worker execs a trusted interpreter into a separate address space, with a
per-worker identity leased through `seat_uid.lease_seat_id`, distinct from the board, CLI
subject and every concurrent worker, no supplementary groups or capabilities, no privilege
elevation, a fresh private home/cwd, an explicit credential-free environment and only bounded
IPC descriptors. It cannot read the board parent's memory, descriptors or credential stores,
including other vendors' stores. Identity/access prerequisites are probed before SDK import; an
absent prerequisite refuses `claude_sdk_worker_unavailable`; a failed separation probe refuses
`claude_sdk_worker_contract_violation`. No fork-only Python worker, inherited board state, token
pipe, jail object, launch callable or live credential reaches it. The trusted parent owns worker
startup and teardown and never imports the SDK. Its existing login proof, credential resolver
and token-pipe forwarding/cleanup remain the sole credential path to the jail. The worker is a
separately sandboxed host helper, not the Claude subject or a Claude jail-profile change. These
are proof obligations, not a claim that a Python object API isolates code. G1 ratifies this
process contract; inability to establish it stops GL-2 rather than silently reverting to an
in-parent SDK.

The owned launcher uses the existing seat-owner namespace/teardown primitives with
`--unshare-net`, private PID/IPC/UTS/mount namespaces and `--die-with-parent`. The network
namespace has no external or host-loopback access; inherited anonymous IPC is its only
communication channel. No network is needed by this custom transport. The filesystem exposes
only read-only verified interpreter/runtime libraries, stdlib, worker payload and SDK closure,
minimal private devices/proc, and fresh size-bounded private tmpfs home/cwd/tmp. No subject
tree, host home, shared temporary directory or host IPC endpoint is mounted. No worker write may
alter an install or survive the run. A read-only snapshot owned outside the worker identities
prevents writable aliases; verification and execution use that same pinned snapshot. The launch
fixture declares finite memory, CPU/wall-time, process/thread, descriptor and tmpfs/disk limits,
enforced by the owner with cgroups/rlimits and mount limits before importing the SDK. Missing
enforcement refuses startup. Workers cannot inspect, signal or access peer workers.

The owner retains cleanup authority across identity changes. Use namespace-level teardown and
in-namespace private-home removal, never ordinary cross-UID signalling. IPC EOF ends the worker;
owner parent-death handling remains effective after credential switching. Parent death
terminates both worker and CLI trees, discards private storage and releases leases only after
reaping. These obligations also hold for the twin. The named open-egress exception covers only
the CLI; the worker has no exception. CLAUDENET preserves and re-probes this worker policy when
confining CLI egress.

## Transport feasibility and authority

At the pinned version, `ClaudeSDKClient(options, transport=...)` selects a custom Transport
before connecting. Its async `connect`, `write`, `close`, `end_input`, synchronous `is_ready`,
and dictionary-yielding `read_messages` can use framed IPC without owning a CLI process. The
parent starts the jailed CLI in the leg's existing launch context before permitting SDK connect;
worker `connect` is a no-op once IPC readiness is established. The parent's `launch_provider`
retains jail/probe/dependency/descriptor ownership. SL-1 extends its one-shot liveness helper
for duplex traffic and owns a distinct host-worker launcher; SL-3 supplies the worker and
transport. Queues, frames and awaits have caps/deadlines; close/end-input never substitute for
raw EOF and reaping. SDK runtime code never constructs or subclasses the stock subprocess
transport. SDK-owned process creation, downloads, host MCP, hooks, executable callbacks and
runtime environment mutation are forbidden. The trusted launcher installs a fail-closed seccomp
policy before SDK import, denying process creation and exec, network access and
namespace/privilege changes; only explicitly listed runtime thread operations are allowed within
the process limit. The filesystem and option gates enforce the remaining prohibitions. Namespace
isolation alone does not enforce a process-creation ban. Tests observe these runtime denies from
outside the worker. Freeze `session_store`, `resume`, `continue_conversation`, `plugins`,
`skills`, `stderr`, `env`, `agents` and tool callbacks absent/empty; disallow ambient imports
and credential-store/keychain/session materialization. SDK timer values
(`CLAUDE_CODE_STREAM_CLOSE_TIMEOUT`, `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`) are fixed in the
worker launch fixture, parsed before CLI launch and refused as `claude_seat_stream_unsafe` on
invalid input; the parent's deadline remains authoritative.

## Parent stream gate

One parent reader owns stdout/stderr bounds, raw secret scanning and original-stream admission.
For each complete stdout line: feed the raw admission checks, parse once with duplicate-key
rejection on every frame and bounded depth, scan all decoded keys/string values (including JSON
escapes), enforce the frozen inbound vocabulary, then forward only that parsed object through
IPC. SL-2 refactors admission to consume that same parsed object rather than reparsing the line,
exposing a route-specific parse policy. Preserve print semantics and activation authority; V3
remains green. SL-3 consumes this interface before its SDK integration. Correlated
initialize/interrupt responses are allowed only for outstanding parent-approved requests.
Inbound `control_request`, `control_cancel_request` and `transcript_mirror` are refused before
SDK or privileged handlers. The first violation closes forwarding and terminates the leg. Stderr
is bounded/scanned and never sent to the SDK. Final text comes only from
`StreamAdmission.result_text`, with source/session binding, one successful conforming result,
raw EOF and actual exit zero. SDK result/iterator completion has no admission authority.
Outbound worker frames use the same bounded UTF-8, duplicate-key, depth and decoded-value rules
and are checked by the parent against a stateful allowlist: one initialize with exact frozen
empty fields, one sealed-prompt user envelope whose complete canonical envelope digest matches
the parent template, and interrupt only on parent cancellation. Request IDs are correlated and
bounded; other controls or repeated/out-of-order frames refuse. No worker message confers launch
or credential authority.

IPC uses a fresh pair of inherited anonymous pipes per worker, with no named or listening
endpoint and no descriptor-passing facility. Only the parent and its leased worker retain their
respective ends; close all other inherited descriptors. Authenticate the channel by this
exclusive capability inheritance and a parent-issued per-launch nonce in the bounded readiness
exchange; a ready message grants no integrity authority. Frames carry that launch binding and
monotonic sequence numbers. Cross-leg or replayed frames refuse. The parent serializes CLI-bound
bytes from its own closed templates, sealed prompt and approved request IDs, never forwards
worker byte strings. Canonicalization uses a frozen JSON encoding and covers the full envelope,
including all fields and the prompt. Differential controls verify that alternate encodings
cannot change the CLI's interpretation. Parent-approved inbound parsed objects alone cross IPC.

## Information handling

The worker receives only the sealed prompt, frozen public configuration and parent-approved
frames. Disable SDK logger propagation and last-resort output, never call `get_server_info`, and
reduce exceptions/worker failures to typed codes without exception text. Worker stderr is
bounded and discarded after private checking. Identity and error-text sentinel controls
establish that logs, mode lines, failure details, records and evidence retain only approved
metadata. Credentials never enter worker state. Public proof metadata contains no raw output;
private cases and findings stay under OD-10.

## Frozen launch delta

One repo-owned `build_sdk_cli_argv` function derives argv from the jailed TUI command and
`SDK_CLI_DELTA`; it alone supplies the actual flags. `cli_path` and CLI-related SDK options are
inert with custom transport and are not controls. Freeze options field by field as configuration
data. The fixture `phase-loop-runtime/tests/data/seats_claude_sdk/launch-v1.json` and its
byte-identical packaged copy `phase_loop_runtime/data/claude_sdk/launch-v1.json` record the
owned argv and a stock `_build_command()` drift oracle (test-only, never connected), plus their
declared differences, CLI/worker environments, options and both IPC/protocol directions. Capture
offline with the real pinned SDK and fake CLI through the owned launcher. Normalize only
declared generated values. Freeze no `-p`, stream-json input/output, verbose, explicit
no-session-persistence, equals-form session/settings flags and their order, the `claude_code`
preset without append, empty initialize agents/hooks/MCP callbacks, prompt envelope and
end-input. Actual argv enforces empty settings sources, strict empty MCP configuration, `--tools
default`, bypassPermissions and remaining jailed TUI flags. Compare semantic closure as well as
bytes; fixture provenance distinguishes repo-built flags from the SDK oracle.

## Unchanged profile and proof limits

Preserve jail environment, mounts, filter and digest. Suppress stock SDK CLI environment
additions, ambient merging and telemetry; record observed entrypoint `unset` separately from
host SDK identity. Offline fake-CLI completion proves the bridge and lifecycle, not real CLI
compatibility, billing or auto-memory behavior. OD-3a must explicitly disposition memory control
using evidence for an approved CLI-native disable or an evidence-backed replacement before
activation. A profile change stops for owner/CLAUDENET. A W0 protocol mismatch stops that arm;
changing a rule requires a reviewed fixture, renewed receipt and, when the ratified fixture
changes, renewed OD-3a authority.

## Install and provenance

Pin SDK 0.2.167, `markdown-it-py==4.2.0` and the full transitive set. SL-3 supplies a frozen
hashed requirements export for the `claude-sdk` extra and per-platform/Python manifests under
packaged `phase_loop_runtime/data/claude_sdk/`; SL-6 documents installation into a dedicated
worker venv via `uv pip sync --python <worker-python> --require-hashes --only-binary :all:
<frozen-export>`. Do not assume `uv tool install` consumes the repository lock: the harness tool
install stays supported, but SDK execution uses this verified worker environment. Generate
reviewed per-file manifests offline from hash-verified wheels, including native dependencies and
the bundled CLI (never executed); wheel hashes and installed-file hashes are distinct bindings.
A trusted bootstrap starts with isolated Python, site processing and bytecode writes disabled
(`-I -S -B`), without project/user paths, `.pth` execution or unreviewed import hooks. Resolve
the closure without importing it using `PathFinder.find_spec` on explicit approved roots (nested
modules resolved from verified package directories); reject conflicting preloaded origins, then
verify all files before adding those roots and importing SDK/lazy runtime modules. Worker
imports remain restricted to this verified closure and trusted stdlib. The trusted parent
authoritatively hashes the full closure once per board-scoped immutable installation snapshot,
before the first worker starts. Every worker binds that verified snapshot; no full bundled-CLI
rehash per leg. Before each worker start compare the complete inventory and each file's
device/inode/size/mtime_ns/ctime_ns/mode signature with the snapshot; any addition, removal or
difference invalidates it and requires a fresh full verification. Snapshot read-only ownership
prevents changes between verification and exec. Restart/reverify on installation change; never
cache across changed bytes. The parent validates bootstrap readiness before that leg's
credential resolver. Missing packages use `claude_sdk_dependency_unavailable` (ORDINARY); wrong
origin/content uses `claude_sdk_provenance_refused` (SECURITY, OD-10), with a verified-install
fix line and private owner reporting. No SDK build-closure remedy or unconditional SDK
dependency-session requirement remains.

Resolve `<worker-python>` only from an operator-owned installation registration, never from
environment, project configuration, PATH or the subject tree. Before exec, the parent verifies
the interpreter executable, `pyvenv.cfg`, stdlib, dynamic loader and required native runtime
libraries against the platform/Python manifest. Origins, symlink targets and permissions must
resolve inside the verified read-only snapshot. The receipt binds this runtime manifest as well
as the SDK wheel/file manifests.

Package adapter/worker/bootstrap payloads in the dedicated
`phase_loop_runtime/data/claude_sdk/worker/` root. Load them by verified path; never add harness
site-packages or the pytest environment to worker `sys.path`. Parent-side resource lookup
verifies the installed harness origin before reading data. Worker imports are limited to the
payload, verified closure and verified stdlib/runtime; readiness reports liveness only, never
substitute for parent verification. Manifest inventory is exhaustive: refuse unlisted files,
`.pth` and any `.pyc`/`__pycache__`, including preexisting bytecode despite `-B`. Normalize
installer-generated bytecode away before sealing the install; only explicitly listed installer
metadata is allowed. Tests plant generic shadow packages and bytecode markers and require
refusal or verified-root selection without executing a marker.

## Receipt and verification

SL-3 owns committed `plans/evidence/seat-qualification/claude-sdk-boundary/receipt-v1.json`,
closed schema `claude-sdk-boundary.v1`. Require SDK version; lock/export/manifest digests;
adapter, worker/bootstrap, parent bridge, seat-module and fixture digests; canonical profile
digest; named launch/duplex/preflight/gate function source digests; interpreter identity and
host class; and separate VB/VL junit digests and collected/passed/failed/skipped counts per
file/selector. Bind the twin launcher/gate and proof tests too. Source regions are
schema-defined, not chosen by the producer; hash shared constants and called helper modules,
with a fail-closed dependency inventory. Every required selector collects nonzero, all pass,
none skip/fail. The receipt excludes only its own bytes, its packaged copy and schema-enumerated
generated proof outputs from inputs (no producer-chosen exclusions); executable code, contract,
schemas, workflows and tests remain included. VB/VL run against the final GL-2 executable tree,
including the activation literals; adding only the receipt, its identical packaged copy and
proof-output metadata afterward is allowed. For receipt production, a test-local fixture
supplies the pending receipt binding; development proof may also substitute admission in that
fixture. These substitutions apply only to synthetic provider-free runs, leave executable source
unchanged and expose no runtime/env knob. Separate controls exercise the real verifier without
substitution, including absent/stale receipts. CI and the board use the same base-installed
`audit-order verify-proof` checker on the private JUnit and current input inventory;
digest/count-only inspection is insufficient. The closed receipt additionally requires
`proof_inputs_sha256`, runtime artifact bindings, worker-install digest, instrumentation-wrapper
digest, and separate private-suite digest, opaque private selector IDs and
collected/passed/failed/skipped counts. SL-3 owns the private suite, session fixture and
observation wrapper; SL-1 owns the checker. Public committed tests carry only generic controls;
case-specific tests live in an operator-private suite (0700 directory, 0600 files) outside the
repository. Its required selection is a distinct VB/VL operand, with nonzero passing counts, its
own JUnit digest and input binding, never assumed to be selected by the committed `-k`
expression. Public receipts contain only digests, counts, host/interpreter vocabulary and opaque
evidence IDs, not private paths or test names.

A session-scoped proof fixture computes `proof_inputs_sha256` at session start from the
executing tree, installed worker snapshot, frozen contract/schema and the complete
schema-defined public/private test and wrapper inventories. Canonical input JSON uses sorted
named SHA-256 bindings, not a commit SHA. Each VB/VL public and private JUnit records this value
through `record_testsuite_property`, the selector and worker-install digest; session end
recomputes and refuses any input drift. No environment or receipt producer argument supplies
these properties. The producer extracts them from completed JUnit, checks them against current
inputs and emits the receipt; it cannot relabel old JUnit. The checker verifies XML digest,
unique required properties, per-selector/file counts, input binding and install digest,
rejecting missing, duplicate or unequal values. Board review recomputes from the final head and
privately supplied suite/wrapper bytes; CI recomputes repository inputs and verifies the same
private artifacts and inventories from a protected evidence store. Both reject JUnit from
another input set even if the receipt is regenerated. Synthetic negative controls cover this
explicitly.

CI retrieves private artifacts by opaque receipt evidence ID using a trusted, read-only
credential in its base-defined job; it executes no PR code and emits only typed metadata. No
artifact or verifier access means failure, not a skipped check. Raw XML and private inventory
never become public CI artifacts/logs. The verifier can check consistency, not cryptographically
prove honest execution: the board still reviews the actual private run evidence. No claim of
private execution rests on public counts.

Install `receipt-v1.json`, `launch-v1.json`, the frozen export and manifests under
`phase_loop_runtime/data/claude_sdk/` in the harness wheel. Read them solely through
`importlib.resources` on the trusted installed package; no cwd, subject-tree, env or
source-checkout fallback. CI requires byte equality of packaged receipt with the committed
receipt and packaged launch data with the test fixture. Runtime/twin preflight recomputes the
explicitly installed subset: export, manifest, worker payload/bootstrap/ adapter, seat module,
installed parent bridge/twin modules and schema-defined function, constant and dependency
regions, launch data and interpreter/runtime/closure manifests. The repository lock, workflows
and test sources remain CI/board bindings, not runtime file lookups. A receipt missing any
installed binding refuses before credentials. Controls place alternate receipt/fixture files in
cwd and subject tree and establish that only packaged copies are read. Missing package data
refuses the route.

## Continuous admission audit

SL-1's `audit_order` verifies the receipt at activation and on every PR while SDK is admitted,
recomputing all repository-derived input digests from the head. An old receipt after a lock,
helper, worker or fixture change fails. Required CI uses a base-defined workflow enforced by a
repository ruleset before GL-2; the required audit job cannot be replaced, skipped or disabled
by PR workflow edits. SL-1 delivers `.github/workflows/claude-sdk-audit.yml` and the base
auditor; the owner enables the required-workflow rule and records its enforcement and private
evidence-store readiness as GL-2 prerequisites. The workflow is defined on the trusted base,
uses fixed artifact-store endpoints and treats head-supplied evidence IDs solely as bounded
identifiers, never URLs or commands. Changes to that trusted policy require owner review. The
job executes the auditor from the event's fetched base tree in isolation, never imports or
executes head code, and inspects head trees as data. Controls changing/removing the PR's audit
step still require this base audit result. Land the base-auditor and closed declarative
admission-facts enforcement before GL-2. Reject unsupported/dynamic/reassigned admission or
authority facts throughout module scope, including conditional mutations; head code cannot opt
out by presenting only an earlier literal. Controls cover changes to head auditor code and
nonliteral admission declarations as well as missing/stale proof. Runtime/twin preflight also
compares the receipt with installed artifact bindings; stale installations remain refused. G1
follows offline fixture capture and pins the fixture sha256 in its section; the auditor compares
that ratified value with the head fixture as well as the receipt. If a prior section was
ratified, append the next OD-3a section, update `SECTION_FOR` explicitly to that section, and
reject citations to the superseded design. No future output commits are pinned.

## Proof and falsifiers

VB uses the real SDK, synthetic credentials and fake CLI in the real jail through
`_parent_infer`; include required-subject-session and session-free cases, the capture-twin path
and two concurrent SDK workers/legs with distinct synthetic credentials and identities,
including workers belonging to different boards. Prove worker identity/access/descriptor
separation, no SDK import in the parent, and resolver-not-called on preflight failure. Refused
selection in a fresh process loads neither SDK nor adapter; enforce an AST rule against
top-level SDK/adapter imports in the seat module. Mutation controls cover provenance without
executing an import marker, parent forwarding/admission order, decoded scanning across frame
types, closed inbound/outbound vocabulary, lifecycle and launch/configuration/profile bindings.
Generic controls verify no synthetic secrets in worker state, logs, exceptions or evidence.
Observe production sandbox denies externally; any in-worker observation uses a separate test
wrapper around the unmodified verified bootstrap, with its digest bound in the receipt. There is
no production instrumentation hook or runtime/env switch. Private case-specific controls have
their separate receipt binding and selection above. Exercise initialization, drain,
duplicate/late results, EOF/nonzero exit, cancellation, worker failure, backpressure and
independent process-tree reaping. Any failed/missing proof leaves SDK unadmitted. Only metadata
and digests are public; OD-10 governs detailed cases/results.

Additional generic falsifiers cover external and planted host-loopback connection refusal, an
unreachable world-readable host canary, rejected writes to install roots,
peer-memory/home/signalling isolation, and parent death with both process trees reaped and all
private storage removed. Prove finite resource bounds and enforced forbids, not merely mocked
calls. Adapter controls explicitly reject a solo-runner route and stock transport substituted at
construction.

VB and VL each provision the worker using the documented hashed `uv pip sync` install, normalize
and verify its manifest, then pass its registered path explicitly through a test fixture into
the owned launcher. They assert its site root differs from pytest's, and record the verified
install digest in JUnit and the receipt. Project `--extra claude-sdk` installs test/oracle
dependencies only and cannot satisfy worker provenance.

## Failure classes

All new codes are non-descending and carry metadata-only fix lines. An absent identity,
namespace, resource-control or worker-launch prerequisite is ORDINARY
`claude_sdk_worker_unavailable`: "Install the documented worker prerequisites and retry." A
worker contract breach, forbidden/replayed/out-of-order outbound frame, forbidden inbound CLI
control frame or failed separation probe is SECURITY `claude_sdk_worker_contract_violation`:
"Stop this route; use private owner review before requalification." Malformed or unapproved
SDK-direction frames are likewise security-class; ordinary timer/stream availability errors
retain their existing code. A missing dependency remains ORDINARY
`claude_sdk_dependency_unavailable`; origin/content or packaged-binding mismatch remains
SECURITY `claude_sdk_provenance_refused`. The existing verified-install fix line applies to
provenance; no fix line requests an API key. Freeze these additions in CODES through security
review before activation. Tests route each security case through OD-10 private evidence plus
owner summary and assert that neither public issue reporting nor exception detail is emitted.
Missing prerequisites remain ordinary, distinct from a probe detecting forbidden access.
