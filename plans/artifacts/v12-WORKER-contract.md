# v12 WORKER frozen contract (IF-0-WORKER-1)

Planning input for `plans/phase-plan-v12-WORKER.md`, sealed by the
`frozen_inputs` digest of the newest `plans/manifest.json` row that names this
file (the plan names that row). It is read-only during execution; a
needed change is an artifact amendment with a new seal, never a lane decision.

Everything here is a harness-local Python/CLI surface. It is not a public wire
type and asserts nothing about unpublished schemas. Field names follow the
roadmap vocabulary, the vendored v1 run-status labels (IF-0-SCHEMA-1) and
JOURNAL's §10 names as provisional fixture labels; CLOSEOUT's v2 reconciliation
supersedes them by amendment. The roadmap's EC-WORKER-1..4 remain the only
acceptance authority; this file never restates them.

Revision 2 applies the agent-harness#1926 board edits and the owner rulings
recorded in the plan's Context (2026-11-08). Revision 3 reconciles §3–§8 with
JOURNAL's revised §10/§11 (agent-harness#1925 at 86d11deda7bbb1088b9cb1e300064c34f52c71e6,
an input pin). Revision 4 (2026-11-09) reconciles the evidence-error terminal
binding with landed JOURNAL (agent-harness#1934). Revision 5 (2026-11-09)
reconciles all JOURNAL calls, nullable reads and failed-append reporting with
landed code; the sweep and sentence changes are recorded in
`plans/artifacts/v12-WORKER-journal-sweep.md`.

## 1. Consumed interfaces

Pre-existing, landed, and not edited by WORKER:

- `supervised_launch` (IF-0-ENVELOPE-1 as landed): `prepare_launch(envelope_bytes,
  *, validator, decoder, config) -> PreparedLaunch | Refused`,
  `consume_admission(prepared) -> LaunchInputs | Refused`, `classify_workspace(
  workspace, target, tier) -> (kind, device, inode)`, `LaunchInputs`,
  `LaunchConfig`, `EnvelopeView`, `ExecutableIdentity`, `Refused`, `sha256`,
  `trusted_bytes`.
- `supervised_dependency.preflight_supervised_route(command) -> Refused | None`
  with keys `supervised-launch`, `supervised-status`, `supervised-cancel`.
- `convergence/adapters/base.py`: `run_bounded`, `AdapterExecutionRequest`,
  `_child_environment`; `codex.py`: `run_codex_adapter`.
- `output_retention.mark(root, run, state, *, owner_pid=None)` and
  `output_retention.prune(root, *, days=None, apply=False, now=None)`. With
  `apply=True`, `prune` returns exactly the runs it retired.
- `panel_invoker.launch_owned` with `SeatLaunchRole.EXECUTOR_TRUSTED`.
- `rfc8785.dumps` (locked dependency `rfc8785>=0.1.4,<0.2`).

Upstream, from IF-0-JOURNAL-1 as JOURNAL's §10 names it (§8):
`run_status.{AttemptIdentity, Units, Ref, Termination, TerminalRefusal,
ResultBinding, Reservation, WriterIdentity, ChainHead, JournalRefused,
default_journal_root, open_journal_root, process_start_identity, make_ref,
reserve_attempt, open_writer, AttemptWriter, read_attempt, resolve_run}` and
`run_status_projection.{attempt_status, read_page, PageResult, proc_observer,
EvidenceResolver}`.

WORKER edits none of `supervised_launch.py`, `supervised_launch_binding.py`,
`supervised_dependency.py`, `executable_dependency_startup.py`,
`supervised_contracts.py`, `schemas/**`, `output_retention.py`, or
`run_status*.py`.

## 2. Shared bounded seam — `convergence/adapters/base.py` (SL-0)

```python
PROPOSAL_CAP_MAX = 67_108_864          # 64 MiB hard ceiling
WORKER_ENV_DROP = frozenset({"SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_ASKPASS",
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM"})
WORKER_ENV_DROP_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

@dataclass(frozen=True)
class CaptureRequest:
    attempt_id: str
    argv: tuple[str, ...]        # admitted LaunchInputs.argv, unchanged
    cwd: Path                    # admitted LaunchInputs.workspace
    timeout_seconds: int         # admitted LaunchInputs.timeout
    stdin: bytes                 # admitted instruction bytes; b"" allowed
    proposal_cap: int            # 1..PROPOSAL_CAP_MAX
    environment: Mapping[str, str]

@dataclass(frozen=True)
class StreamDigest:
    sha256: str
    byte_count: int

@dataclass(frozen=True)
class SpawnRefused:
    reason: str

@dataclass(frozen=True)
class BoundedCapture:
    attempt_id: str
    termination: str             # completed | cancelled | timed_out | failed_to_start
    terminated_by: str           # worker | harness | operator
    signal: str | None
    exit_code: int | None
    stdout: StreamDigest
    stderr: StreamDigest
    streams_complete: bool       # both pipes reached EOF before the deadline
    proposal: bytes | None       # stdout bytes iff stdout.byte_count <= proposal_cap
    proposal_overflow: bool
    stdin_delivered: bool
    spawn_count: int             # 0 or 1
    duration_ns: int | None      # monotonic, from spawn
    observed_start_utc: str | None
    observed_end_utc: str | None # informational only

def worker_child_environment(allow: frozenset[str]) -> dict[str, str]: ...
def run_bounded_capture(request: CaptureRequest, *,
                        before_spawn: Callable[[], SpawnRefused | None],
                        cancel: threading.Event) -> BoundedCapture | SpawnRefused: ...
```

Rules:

- Spawn uses the same primitive and discipline as `run_bounded`:
  `launch_owned`, `EXECUTOR_TRUSTED`, own session, the unreaped leader held via
  `waitid(WNOWAIT)`, and `killpg` of the launcher's own group on every exit
  path. Execute-mode timing only; never the review path or review isolation. No
  second process runner.
- `before_spawn` runs immediately before the spawn call. A `SpawnRefused`
  return or any exception means no spawn, `spawn_count == 0`, and the call
  returns `SpawnRefused`. A `None` return permits exactly one spawn.
- One monotonic deadline is armed at spawn (`timeout_seconds`) and never
  restarted. Expiry before the leader exits: `timed_out`/`harness`/`SIGKILL`.
  `cancel` set: `cancelled`/`operator`/`SIGKILL`. Natural leader exit:
  `completed`/`worker` with `exit_code`, then `killpg` of the own group. A spawn
  `OSError` returns `failed_to_start`/`harness` with `spawn_count == 1`.
- Draining is bounded by that same deadline. After the leader exits, both pipes
  drain to EOF or until the deadline. If the deadline passes first (for example,
  an escaped descendant still holds a pipe), the launcher closes both pipes and
  sets `streams_complete=False`; the termination stays as observed.
- Every byte read from stdout and stderr is digested and counted. Only stdout
  bytes up to `proposal_cap` are retained; past the cap, draining and digesting
  continue and `proposal_overflow` is set. stderr bytes are never retained.
  Neither stream is decoded or copied into any record.
- `stdin` is written once through the same selector loop, then closed. An EPIPE
  ends delivery and sets `stdin_delivered=False`. Instructions never enter argv.
- `worker_child_environment(allow)` takes `_child_environment()`, removes
  `WORKER_ENV_DROP` and the prefixed names, then keeps only names in `allow`
  plus the scratch-relocation names `child_scratch_env` adds. `allow` defaults
  to empty (§3). Records carry variable names only, never values or value
  digests. Values stay unbound to admission until CLOSEOUT v2's classified
  environment (ruling OQ-1).
- `run_bounded`, `AdapterExecutionRequest` and `run_codex_adapter` keep their
  signatures, statuses, fixed details, 64 KiB cap, DEVNULL stdin, basename
  check and review isolation byte-for-byte in behavior. Sharing internals is
  allowed only behind parity tests.
- A `setsid` descendant can leave the group. `BoundedCapture` makes no claim
  about descendants outside the launcher's own process group.

## 3. Patch-return adapter and lifecycle — `patch_return.py`, `codex.py` (SL-1)

```python
CANCEL_WAIT_SECONDS = 10         # constant ceiling for any cancel wait

@dataclass(frozen=True)
class WorkerSettings:            # parsed from the caller-held config bytes whose sha256 == LaunchInputs.config_digest
    proposal_cap: int            # key "worker_proposal_cap", 1..PROPOSAL_CAP_MAX, default PROPOSAL_CAP_MAX
    audit_entry_cap: int         # key "worker_audit_entry_cap"
    audit_byte_cap: int          # key "worker_audit_byte_cap"
    environment_allow: frozenset[str]   # key "worker_environment_allow", default empty
    retention_days: int | None   # key "worker_retention_days"
    reference_roots: tuple[Path, ...]   # existing key "reference_roots"

@dataclass(frozen=True)
class WorkerAttemptIdentity:
    assignment_digest: str; envelope_digest: str; launch_digest: str; raw_digest: str
    run_id: str; attempt_id: str
    target_unit_ids: tuple[str, ...]; readonly_neighbor_unit_ids: tuple[str, ...]
    snapshot_ref: str            # from the envelope member "snapshot_reference"
    caller_context_sha256: str   # sha256(rfc8785.dumps(admitted caller_context))

@dataclass(frozen=True)
class BaselineIdentity:
    path: str; git_blob_sha1: str | None; sha256: str | None

@dataclass(frozen=True)
class ProposalReturn:
    status: str                  # see §3.2
    proposal_bytes_digest: str | None
    byte_length: int
    baselines: tuple[BaselineIdentity, ...]
    locator: str | None          # evidence-root-relative in the result record only; never authority

@dataclass(frozen=True)
class JournalAnchor:
    terminal_seq: int            # ChainHead.last_seq of the terminal append
    chain_head_sha256: str       # ChainHead.segment_sha256 of the terminal append

@dataclass(frozen=True)
class WorkerResult:
    identity: WorkerAttemptIdentity | None   # None only before step 2 succeeds
    state: str                   # finished | refused
    termination: run_status.Termination | None   # passed through unchanged
    refusal: str | None
    worker_invocations: int
    proposal: ProposalReturn | None
    evidence_envelope_digest: str | None
    journal_anchor: JournalAnchor | None
    journal_complete: bool       # False after any writer failure (§3.1 rule W)

CancelOutcome = Literal["cancelled", "already_terminal", "cancel_pending",
                        "unknown_attempt", "owner_unverified", "owner_not_live"]

def default_state_root() -> Path: ...
def evidence_resolver(state_root: Path) -> run_status_projection.EvidenceResolver: ...   # (AttemptIdentity, Ref) -> str
def run_patch_return(prepared: PreparedLaunch, *, config_bytes: bytes,
                     state_root: Path, cancel: threading.Event | None = None) -> WorkerResult: ...
def cancel_attempt(*, state_root: Path, run_id: str | None = None,
                   attempt_id: str | None = None, wait_seconds: float = CANCEL_WAIT_SECONDS,
                   launcher_commands: tuple[tuple[str, ...], ...] = PRODUCTION_LAUNCHER_COMMANDS
                   ) -> CancelOutcome: ...
# codex.py
def run_codex_patch_return(prepared: PreparedLaunch, *, config_bytes: bytes,
                           state_root: Path, cancel: threading.Event | None = None) -> WorkerResult: ...
```

`run_codex_patch_return` refuses `provider_mismatch` with zero effects unless
`Path(LaunchInputs.executable.path).name == "codex"`, then delegates. The
generic `run_patch_return` is provider-neutral: executable identity comes from
admission digests, not basenames. WORKER performs no config-file read: the
caller reads the config once with `trusted_bytes` and passes those bytes.
`cancel_attempt` refuses `wait_seconds` outside (0, `CANCEL_WAIT_SECONDS`].

### 3.1 Order

Steps 1–2 have no attempt-scoped effects on refusal.

1. `consume_admission(prepared)`. On `Refused`: return `state=refused`, nothing
   reserved, no journal/evidence/launcher effects.
2. Settings and identity:
   - require `sha256(config_bytes) == LaunchInputs.config_digest`
     (`config_changed`), then parse `WorkerSettings` from those same bytes
     (`worker_settings_invalid`);
   - set `caller_context_sha256` to the sha256 of `rfc8785.dumps` over the
     admitted `caller_context`, thawed to plain dict/list exactly as decoded.
     A value RFC 8785 cannot encode refuses `caller_context_unencodable`;
   - require `state_root` outside the workspace, target and `reference_roots`,
     with operator uid and mode 0700 (`state_root_unsafe`);
   - `open_journal_root(<state_root>/journal, create=True, excluded=(workspace,
     target, *reference_roots))`. A `JournalRefused` refuses with its code. For
     `default_state_root()` this path equals `default_journal_root()`; a test
     asserts that equality.
3. `reserve_attempt(root, AttemptIdentity(...), units=Units(...),
   launch_digest=..., caller_context_sha256=...)`. A `JournalRefused` (duplicate,
   terminal, crash-reserved or unavailable) refuses with zero invocations and
   no further effects. Then `open_writer(root, reservation)` in the same
   launcher process (JOURNAL refuses `writer_identity_mismatch` elsewhere) and
   `writer.state("queued", worker_invocations=0)`.
4. Launcher record `launchers/<attempt_id>.json` (§5).
5. Before-audit (§3.3). An error refuses `audit_error`.
6. Inside `before_spawn`:
   - if `cancel` is set, refuse `cancelled_before_start`;
   - recheck `classify_workspace` kind, device and inode, and the full-file
     sha256 of the executable and each wrapper, through component-wise
     O_NOFOLLOW reads. Mismatches refuse `workspace_changed`, `device_changed`,
     `inode_changed`, `executable_changed` or `wrapper_changed`;
   - as the last action, `writer.state("running", worker_invocations=1)`.
7. `run_bounded_capture`. From the spawn call onward, every outcome is
   `finished` with the capture's termination; refusal never follows start.
   A cancel while running journals `writer.state("cancelling", ...)` and the
   phrase `cancellation requested` before the group is killed.
8. After-audit and comparison (§3.3), then the proposal decision (§3.2).
9. Evidence (§4):
   - create the run directory;
   - `mark(evidence_root, run, "active", owner_pid=os.getpid())`;
   - write `proposal.bin` (only when `returned`) and `evidence.json`, both
     0600, and fsync;
   - `mark(..., "sealed")`;
   - write the ledger entries (§4).
   Evidence is created only here, so refused attempts leave no evidence
   directory. A failure here removes `proposal.bin`, sets the status to
   `withheld_evidence_error`, clears the proposal digest and locator, and sets
   `WorkerResult.evidence_envelope_digest` to null; no `ResultBinding` is built.
   Partial evidence or ledger files never authorize a result: this path emits
   no evidence refs and its terminal has `result_binding=None`, even if the
   capture completed successfully.
10. Journal the evidence events, then the terminal line:
    - unless `withheld_evidence_error`, `writer.event("attempt evidence bound",
      refs=(make_ref("evidence_envelope", evidence_bytes, None),))`;
    - when `returned`, `writer.event("proposal bytes captured",
      refs=(make_ref("proposal_bytes", proposal, None),))`;
    - for `withheld_audit_error` or `withheld_unexplained_change`, the phrase
      `workspace audit failed; proposal withheld`; for every other `withheld_*`
      status, the phrase `proposal withheld`. Neither carries refs, and
      `absent` emits no withholding phrase;
    - `writer.terminal("finished", worker_invocations=worker_invocations,
      termination=termination, refusal=None,
      result_binding=ResultBinding(...))`, except that
      `withheld_evidence_error` passes `result_binding=None`; `finished` records
      process termination only, and a null binding must never authorize a
      valid result;
    - `JournalAnchor` from the returned `ChainHead`, then `writer.close()`.
11. Best-effort `prune(evidence_root, days=retention_days, apply=True)`. Every
    run it returns gets a ledger retirement mark (§4). Failure never alters the
    result.

Healthy-writer refusals at steps 4–6 append `writer.terminal("refused",
worker_invocations=0, termination=None, refusal=TerminalRefusal(...),
result_binding=None)`, from `queued`. That is the only refusal the journal
records.

**Rule W (writer failure).** This rule matches JOURNAL §6 poisoning. From step
3 onward, a writer failure is any of:

- a `JournalRefused` from `open_writer`, `state` or `terminal`;
- a `JournalRefused` from `event` other than `event_cap_reached`;
- any raised exception.

`writer_poisoned` and the I/O refusal that poisoned the writer are writer
failures. After the first one, WORKER makes no further `state`, `event` or
`terminal` call; a poisoned writer would refuse them anyway. It calls only
`close()`, which releases the lock. The failed append may already be on disk,
for example a `running` line whose fsync failed, or a partial line that readers
report as `journal_torn_line`. An `event_cap_reached` refusal drops only that
event; JOURNAL reserves the slot for the terminal line.

- Before spawn: no spawn, no evidence. Return `state=refused`,
  `refusal="journal_unavailable"`, `journal_anchor=None`,
  `journal_complete=False`.
- After spawn: the capture, audit and evidence steps complete. Return
  `state=finished` with the capture's termination, `journal_anchor=None` and
  `journal_complete=False`.

In either case a complete line written before an append or fsync failure may
remain readable, and `attempt_status` reports the last verified line. A
nonterminal (`queued`, `running` or `cancelling`) displays as itself while the
owner is live and as `stale_unknown` after owner exit or pid reuse. A terminal
displays `refused` or `finished (<termination reason>)` whatever the owner's
liveness, so a pre-spawn failure can leave a `refused` line whose reason differs
from `WorkerResult.refusal`. Torn or otherwise unverifiable history, or history
with no state line, displays `unknown`. Poisoning is writer-local; `close()`
neither removes landed lines nor records poisoning. No anchor was returned and
`journal_complete=False`, so the controller treats the outcome as uncertain. A
reader-derived `chain_head` or terminal display never substitutes for the
missing anchor, and WORKER never appends to or relabels the journal to match its
result. Run status is never a work outcome (`runtime_not_work_outcome`).

Descriptor execution (ELF through an inherited fd path) is used where
supported. Otherwise evidence records `exec_binding: "path_recheck"` and
readiness discloses the remaining check-to-exec window.

### 3.2 Proposal decision (first matching rule wins)

The proposal is a git-style unified diff on stdout (ruling OQ-3).

| Condition | `status` |
| --- | --- |
| termination is not `completed`, exit_code != 0, or `streams_complete` is False | `withheld_incomplete` |
| `proposal_overflow` | `withheld_oversized` |
| either audit errored | `withheld_audit_error` |
| an unexplained change | `withheld_unexplained_change` |
| stdout empty | `absent` |
| structural check fails | `withheld_malformed` |
| otherwise | `returned` |

Step 9 can still turn `returned` into `withheld_evidence_error`.

A cancelled or timed-out attempt never returns any part of a patch (ruling MM-3).

A change is unexplained in the protected target tree or refs in either tier,
and anywhere in the workspace for `provider_readonly_patch_return_audit`. Under
`post_write_audit_only`, workspace changes are detection-only: evidence counts
them as `workspace_writes_detected`.

Structural check: the proposal is UTF-8 with at least one `diff --git a/<p>
b/<q>` header. Every header and `---`/`+++` path is a normalized relative POSIX
path: not empty, no `.` or `..` component, no `.git` component (case-insensitive),
no NUL, no leading `/`, at most 4096 bytes. `/dev/null` is allowed only in
`---`/`+++` lines. WORKER performs no span, grant, post-image or apply check.
Those belong to the external controller.

Baselines: for each distinct header path, in order of first appearance, record
the git blob SHA-1 (`blob <len>\0` framing) and the SHA-256 of the regular file
at that path in the before-audit workspace snapshot. Both are null when no
regular file existed there. Withheld bytes are never written to disk.

### 3.3 Audit

The audit promise is "tree and refs" (owner ruling). It runs in process and
never executes git or reads git configuration. A snapshot is the sorted list of
(relative path, type ∈ {file, dir, symlink}, permission bits, size, file
sha256 or link target) for:

- (a) the workspace tree;
- (b) the protected target tree;
- (c) the target's `HEAD`, `packed-refs` and `refs/**`, read from the git
  directory physically inside the target. A gitfile pointing elsewhere is an
  audit error.

Walks use dir_fd and O_NOFOLLOW. Other file types, unreadable entries and
exceeding `audit_entry_cap`/`audit_byte_cap` are audit errors.

**Disclosure.** `.git/objects/**` is excluded by name in both trees and is not
audited at all: object additions, modifications and deletions all go
undetected. `HEAD`, `packed-refs` and `refs/**` are audited.

## 4. Evidence, ledger, result record and layout

**State root.** `default_state_root()` is
`<pw_dir>/.local/state/agent-harness/supervised-worker`, with `pw_dir` taken from
`pwd.getpwuid(os.geteuid())`, never from `$HOME`. Production selection of a
non-default root (for example LANEEXEC's per-client inventories) is
digest-bound operator configuration designed in LANEEXEC (owner ruling). Until
that amendment exists, the CLI uses `default_state_root()`. In-process callers
and tests pass `state_root` directly.

Layout (dirs 0700, files 0600):

- `<state_root>/journal/` — JOURNAL's root (J6); outside every prune root.
- `<state_root>/launchers/<attempt_id>.json` — launcher records (§5). One per
  attempt, so a retry under the same run never collides.
- `<state_root>/evidence/` — the only `output_retention` root. One run directory
  per attempt, named `a-` + the first 32 hex digits of
  sha256(assignment_digest `\0` run_id `\0` attempt_id). It holds `evidence.json`
  and optional `proposal.bin`.
- `<state_root>/evidence-ledger/<run>.json`: created O_EXCL after sealing.
  It lists the refs this attempt journals, as `{kind: sha256}`.
- `<state_root>/evidence-ledger/<run>.retired`: an O_EXCL mark, added only for
  a run that WORKER's own `prune(apply=True)` returned as retired.

`evidence_resolver(state_root)(identity, ref)` derives `<run>` from the
`AttemptIdentity` (same digest as above), then returns:

- `unknown` when the ref's (kind, sha256) is not in `<run>.json`;
- `retention_dropped` when `<run>.retired` exists;
- `present` when the run directory exists, is `sealed`, and matches its
  retention record;
- `unknown` otherwise, including deletions WORKER did not record.

Equal proposal digests in different attempts resolve independently, per
identity.

Journal refs always carry `locator: null`; the pinned locator is
repository-relative or null. `evidence.json` is a local, metadata-only record
labelled `"local_record": "agent-harness.supervised-worker.evidence",
"version": 0, "fixture_labelled": true`. It holds:

- `WorkerAttemptIdentity`;
- `argv` (prompt-free by construction) and `instruction_digest`;
- executable `{realpath, sha256, version}` and wrappers `[{realpath, sha256}]`.
  `version` comes from the config's held `qualified_version`; no probe is run.
  It is null with `version_source: "unqualified"` for the audit tier;
- config, template and qualification digests;
- workspace kind, device and inode, and the tier;
- `environment_names`, `exec_binding`;
- termination, `exit_code`, `worker_invocations`;
- stdout and stderr `StreamDigest`s, `streams_complete`, `duration_ns`,
  `stdin_delivered`;
- the `ProposalReturn`, `audit {status, before_sha256, after_sha256,
  workspace_writes_detected, unexplained_count}`.

`evidence_envelope_digest` is the sha256 of its exact bytes. No prompt,
instruction, stdout, stderr, proposal content, environment value, secret or
caller_context content appears. caller_context appears only as
`caller_context_sha256`.

The `--result` record carries the same label pattern
(`agent-harness.supervised-worker.result`, version 0). It is `WorkerResult`
serialized, including `journal_anchor` as the controller-held anchor.

## 5. Native cancel and launcher identity

The launcher:

1. takes its nonce from `Reservation.writer.writer_instance_id`. That value is
   128-bit random lowercase hex, minted once by `reserve_attempt` and copied
   unchanged by `open_writer` (J3). A later cancel reads it from
   `read_attempt(root, attempt_id).writer`. Identity and writer are None
   together, when JOURNAL returns no index entry for the id (for example an
   invalid or never-reserved id, an unverifiable index or an unreadable attempt
   directory); cancel then returns `unknown_attempt` on the first look, with
   zero signals and no launcher-record read;
2. at step 4 creates `launchers/<attempt_id>.json` with
   O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600, holding {run_id, attempt_id,
   assignment_digest, pid, process_start_time (`process_start_identity(pid)`),
   exe_realpath, exe_sha256, cmdline_sha256, nonce};
3. holds an exclusive POSIX `fcntl` lock on that file for its lifetime.

**Disclosure.** The nonce is not secret: the writer identity appears in every
journal line, which same-login processes can read. The substantive checks are
the record lock held by the live pid and the live process identity below.

`SIGTERM` sets the launcher's cancel event. Before spawn this refuses
`cancelled_before_start`. While running, the launcher journals `cancelling`,
then the capture kills only its own group. A cancel arriving between
reservation and record creation finds no record and returns `owner_unverified`.

`cancel_attempt` opens `<state_root>/journal` with `create=False`; a
`JournalRefused` gives `unknown_attempt` with zero signals. It resolves the
target as follows:

- `--attempt` reads `read_attempt` and `attempt_status`;
- `--run` takes the last id from `resolve_run`. An absent run, which returns
  `()`, or a `JournalRefused` gives `unknown_attempt`.

On the first look, the outcome is:

- `read_attempt(...).identity` is None: `unknown_attempt`;
- already terminal: `already_terminal`;
- `attempt_status` display `stale_unknown` (dead or reused owner):
  `owner_not_live`, with zero signals;
- otherwise, verification proceeds.

Verification checks, all required, zero signals on any failure
(`owner_unverified`):

1. the record has operator uid, 0600 mode, a no-follow path and a well-formed
   body;
2. the `read_attempt` writer identity (owner_pid, process_start_time,
   writer_instance_id) equals the record's (pid, process_start_time, nonce);
3. `pidfd_open(pid)` succeeds; this pidfd is the only signal target;
4. live `process_start_identity(pid)` equals the record;
5. `/proc/<pid>/exe` realpath equals the record and the canceller's own
   interpreter realpath;
6. sha256 of the live cmdline equals the record, and that cmdline follows the
   interpreter with one entry of `launcher_commands`;
7. the record lock holder (`F_GETLK` `l_pid`) equals pid.

Then `pidfd_send_signal(SIGTERM)` and wait up to `wait_seconds` for a terminal
line. The outcome is:

- `cancelled`, for `finished` with termination reason `cancelled`, or
  `refused` with reason `cancelled_before_start`;
- `already_terminal`, for any other terminal;
- `cancel_pending`, if no terminal line appears before the wait ends.

Repeats are idempotent: they re-verify and re-signal. A pid or pgid read from
the journal is never signalled.

`PRODUCTION_LAUNCHER_COMMANDS = (tuple(seat_uid.trusted_module_argv(
"phase_loop_runtime.supervised_worker_cli", "launch")[1:]),)`. The launcher starts
through the trusted-installation boot (agent-harness#1132), never `-m`, so the
argv after the interpreter is `-I -c <trusted boot> <package root>
phase_loop_runtime.supervised_worker_cli launch`; check 6 matches that exact entry.
The CLI always passes this constant and `CANCEL_WAIT_SECONDS`.
Only in-process tests may pass a fixture launcher command; no CLI flag,
environment or config can.

## 6. CLI — `supervised_worker_cli.py` (SL-2)

`python -I -m phase_loop_runtime.supervised_worker_cli` with
`main(argv: Sequence[str] | None = None, *, state_root: Path | None = None) -> int`
and the constant `STATUS_PAGE_SIZE`.
The keyword-only `state_root` is the in-process test seam; no argv, environment
or config reaches it. The verbs are exactly:

- `launch --envelope <path> --result <path>`;
- `status (--run <id> | --attempt <id>) [--page [--cursor <token>]]`;
- `cancel (--run <id> | --attempt <id>)`.

Unknown verbs or flags refuse. It refuses unless `sys.flags.isolated`, and
imports only stdlib, `rfc8785` and `phase_loop_runtime`. It does not replace
`phase-loop status`, adds no console script and no `pyproject.toml` change.

- Every verb first calls `preflight_supervised_route` with its key, before any
  file, import-binding, journal, evidence or output effect.
- `launch` then resolves `_production_codec()`. In WORKER it is `None`, so the
  verb refuses `codec_unavailable`, with zero envelope reads, binding loads,
  probes, spawns, journal, evidence or result writes. CLOSEOUT SL-2, owner of
  this file, replaces `_production_codec` using CLOSEOUT SL-1's
  `load_v2_binding`, and wires the remaining launch steps. WORKER freezes and
  tests these building blocks in process:
  - `read_envelope_file(path: Path, *, cap: int) -> tuple[bytes, int] | Refused`
    returns (bytes, st_mode). It requires operator uid, a regular file,
    component-wise O_NOFOLLOW and the cap, and refuses group/world write. After
    decode, any inline instruction member read from a group/world-readable file
    refuses `envelope_mode_unsafe`.
  - `open_result_file(path: Path, *, excluded: tuple[Path, ...]) -> int | Refused`
    requires an absolute path with a verified 0700 operator parent opened by
    dir_fd. It opens O_CREAT|O_EXCL|O_NOFOLLOW with mode 0600, outside the
    workspace, target, reference roots and state root.
- `status` is provider-free. It opens the journal root with `create=False`; a
  `JournalRefused` (for example `journal_missing` before any launch) prints its
  code and exits as a refusal. Otherwise it prints one JSON object
  `{"attempt": <attempt_status>, "page": <page | null>,
  "next_cursor": <str | null>, "page_diagnostics": <list[str] | null>}`:
  - `--attempt` uses `attempt_status(root, id)`, with JOURNAL's liveness
    observer;
  - `--run` uses the last id from `resolve_run`. An absent run (`()`) or a
    refusal prints `unknown_attempt` and exits as a refusal;
  - `--page` requires a non-null `read_attempt(root, id).identity`; if absent,
    print `unknown_attempt` and exit as a refusal. Otherwise call `read_page`
    with UTF-8 JSON bytes encoding `{assignment_digest:
    read_attempt(root, id).identity.assignment_digest, page_size:
    STATUS_PAGE_SIZE, cursor}` and `evidence=evidence_resolver(state_root)`.
    A `JournalRefused` prints its code and exits as a refusal; a `PageResult` supplies `page`, `next_cursor` and `page_diagnostics` (JOURNAL's closed codes; an attempt with diagnostics contributes no events);
  - `--cursor` passes a `next_cursor` from a previous page; otherwise `cursor`
    is null.
  - `STATUS_PAGE_SIZE = 50`, within JOURNAL's bound of 100.
  Display text comes only from JOURNAL's closed phrase sets.
- `cancel` prints the `CancelOutcome`.
- Subprocess CLI tests exercise only paths that end before state-root
  resolution: route refusal, `codec_unavailable`, usage and isolation. They
  never create or read anything under the real default root. `status` and
  `cancel` are tested in process through `state_root`.
- Exit codes are provisional fixture labels and not part of IF-0-WORKER-1:
  0 for a written record, 2 for usage, 10 for refusal, 20 for an uncertain
  outcome (for example `journal_complete=False`). Consumers read records, not
  exit codes.

## 7. Test and mutation obligations

Path-entered tests use real offline subprocesses (synthetic provider scripts in
`tests/fixtures/supervised_worker_local/`, labelled non-authoritative) and the
real landed JOURNAL writer. Writer faults are injected below that real writer,
by failing `os.write` or `os.fsync` for the journal segment, so JOURNAL's own
poisoning runs and a landed-then-failed `running` line is genuine. Only
`event_cap_reached` uses a delegating wrapper. No live provider, credential or
network is used.

Isolated-Python children insert the checkout's absolute source root and assert
`phase_loop_runtime.__file__` lies beneath it (ENVELOPE rule). Mode-checking
tests pin umask 077 and restore it. Tests run serially, never with `-n`.

| ID | Lane | Obligation | EC |
| --- | --- | --- | --- |
| W1 | SL-0 | Capture: stdout/stderr digests over all bytes, cap + overflow, stdin one-shot and not in argv, deadline, cancel, group reclaim, failed start, `before_spawn` refusal = zero spawns; a pipe-holding escaped descendant ends at the deadline with `streams_complete=False` | EC-WORKER-1, EC-WORKER-4 |
| W2 | SL-0 | `run_bounded` parity: every existing status/detail/bound unchanged | EC-WORKER-1 |
| W3 | SL-0 | Planted `SSH_AUTH_SOCK`, `GIT_ASKPASS`, `SSH_ASKPASS`, `GIT_CONFIG_*` credential-helper, vendor and GH tokens absent from the child; empty default allowlist passes only scratch names | EC-WORKER-4 |
| W4 | SL-1 | Order §3.1: zero invocations for every refusal at steps 1–3, zero attempt effects at steps 1–2, and no further WORKER effects after a reservation refusal (failed reservation may leave JOURNAL claims); healthy-writer refusals journal `refused` from `queued`; Rule W for a failing `queued`, a `running` append that lands then fails (no spawn, `running` while the owner is live, `stale_unknown` after owner exit or pid reuse), a healthy-writer `refused` terminal that lands then fails (WORKER `refused`/`journal_unavailable`; JOURNAL keeps `refused` with the original reason), and a post-spawn terminal failure (WORKER `finished`, no anchor, `journal_complete=False`; a complete terminal keeps `finished (<reason>)` after owner exit or pid reuse; torn history displays `unknown`) | EC-WORKER-2, EC-WORKER-4 |
| W5 | SL-1 | Replay one envelope sequentially, concurrently across 4 processes, and after a crash between reservation and spawn: at most one spawn in total; a retry under the same run with a new attempt id launches | EC-WORKER-2, EC-WORKER-3, EC-WORKER-4 |
| W6 | SL-1 | Pre-spawn recheck of each identity element | EC-WORKER-2 |
| W7 | SL-1 | Proposal decision table, every row including `streams_complete=False` and `withheld_evidence_error` (fault each step-9 operation; real JOURNAL accepts `finished` with unchanged termination and null binding, no evidence refs, no proposal digest or locator, and no readable valid result even with partial files); baselines; malformed and oversized | EC-WORKER-1, EC-WORKER-4 |
| W8 | SL-1 | Audit: workspace change per tier, target change, ref change, gitfile escape, cap and special-file errors | EC-WORKER-1, EC-WORKER-4 |
| W9 | SL-1 | Evidence binding fields of §4; prompt, stdout and stderr sentinels absent from journal, evidence and result; refs carry `locator: null` | EC-WORKER-2, EC-WORKER-4 |
| W10 | SL-1 | Cancel: real fixture launcher raced in queued (→ `cancelled`), running (→ `cancelled`) and terminal (→ `already_terminal`) states; idempotent repeat; forged record naming an unrelated same-user process (zero signals); stale owner (`owner_not_live`); pid reuse | EC-WORKER-3, EC-WORKER-4 |
| W11 | SL-1 | setsid descendant escapes, recorded as the limitation; the test reaps its own escapee | EC-WORKER-3, EC-WORKER-4 |
| W12 | SL-1 | Retention: active then sealed in step 9 only; refused attempts leave no evidence; evidence events emitted; WORKER's prune leaves the journal intact and JOURNAL's page shows `retention_dropped` with digests kept; a deletion WORKER did not record reads `unknown`; retry = fresh admission + new attempt, evidence preserved | EC-WORKER-3, EC-WORKER-4 |
| W13 | SL-2 | Subprocess isolated CLI: `codec_unavailable` with zero probes and effects; required sessions refuse launch/cancel before reads; shadowed stdlib and validator modules in the workspace cwd do not load; nothing under the real root. In process: envelope owner/mode/symlink/size; result O_EXCL/0600/no-follow/outside roots; `main(["cancel", ...], state_root=tmp)` against a live fixture launcher holding a valid record returns `owner_unverified` with zero `pidfd_send_signal` calls and the launcher still running; `status` prints `attempt_status` and an optional page | EC-WORKER-2, EC-WORKER-3, EC-WORKER-4 |
| W14 | SL-2 | Receipt validation against producer results, deferred-obligation list (§9) and source bindings | EC-WORKER-4 |
| W15 | SL-1 | `caller_context_sha256` equals sha256 of `rfc8785.dumps` over the admitted value; an unencodable value refuses before reservation; `__proto__` members survive and a changed number changes the digest | EC-WORKER-2 |

Mutation controls: each production guard named below gets a source-copy mutant
in its lane's own test file. The mutant must turn a previously passing
path-entered assertion red. Mutating a test-side oracle never counts.

- SL-0: proposal cap, stderr digest, deadline arm, drain deadline bound, cancel
  kill, killpg reclaim, stdin channel, each drop name/prefix, allowlist,
  `before_spawn` gate.
- SL-1:
  - ordering: consume-before-reserve, reservation-before-spawn,
    reservation-failure gate, each step-6 recheck, running-before-spawn;
  - journal: Rule W stop, each evidence event, cancel-before-start mapping;
  - decisions and evidence: each §3.2 row, each §3.3 scope, evidence field
    binding, active-before-write, seal-after-writers, ledger retirement mark,
    resolver `unknown` fallback, JCS digest;
  - cancel: each §5 verification check, pidfd target;
  - provider basename (codex).
- SL-2: isolated flag, preflight-before-read, codec gate, each envelope-file
  check, each result-open flag, status liveness source.

## 8. JOURNAL interfaces consumed (J1–J6)

These are reconciled with landed JOURNAL at origin/main
504355e020c271b649dd01e5f494c516d5164319, an input pin. The work-start
gate re-checks them against the landed code. A later rename is a WORKER artifact
amendment, not an in-lane workaround.

- J1 — `reserve_attempt(root, identity, *, units, launch_digest,
  caller_context_sha256) -> Reservation | JournalRefused` and
  `open_writer(root, reservation, *, limits=DEFAULT_LIMITS) -> AttemptWriter | JournalRefused`.
  A successful reservation durably claims the attempt id globally via atomic
  creation; a failed reservation may leave a run claim, attempt claim or index
  bytes, and WORKER never rolls them back or reuses the attempt id. A torn index tail or short run record then refuses later reservations for that assignment or run (`index_unverifiable`, `run_record_unreadable`) until operator quarantine (JOURNAL §5); WORKER refuses with that code.
- J2 — `AttemptWriter.state`, `.event`, `.terminal` and `.close`. Appends
  return `ChainHead(segment_index, segment_sha256, last_seq)` or
  `JournalRefused`. Any I/O failure poisons the writer: later calls refuse
  `writer_poisoned`, and `close()` only releases the lock (Rule W).
- J3 — `Reservation.writer` (`WriterIdentity`). `writer_instance_id` is minted
  once by `reserve_attempt` and copied unchanged by `open_writer`, which refuses
  `writer_identity_mismatch` in another process. `process_start_identity(pid)`
  is importable, and `read_attempt(...).writer` returns the identity later.
- J4 — `resolve_run`, which returns `()` for an absent run; `read_attempt`,
  whose `.identity.assignment_digest` is the page key; and `attempt_status`
  with keyword-only `observer=proc_observer` liveness (`stale_unknown` for a
  dead or reused owner of a verified nonterminal; verified terminals retain
  their terminal display). `read_attempt` always returns `AttemptRead`, whose
  identity and writer may be None on unknown reads; check before dereferencing.
- J5 — `read_page(root, request: bytes, *, evidence)`, with
  `EvidenceResolver = Callable[[AttemptIdentity, Ref], str]` and a
  UTF-8 JSON `page_request` bytes encoding `{assignment_digest,
  1 <= page_size <= 100, cursor}` (all keys required; cursor nullable).
  It returns `PageResult(page, next_cursor, diagnostics) | JournalRefused`;
  `next_cursor` is nullable, and `omitted.retention_dropped` counts refs in the
  returned page that the resolver reports dropped.
- J6 — `default_journal_root()`, with no arguments, from `pw_dir`, equals
  `<default_state_root()>/journal`. `open_journal_root(path, *, create,
  excluded)` takes WORKER's `<state_root>/journal`, outside every
  output_retention root.

WORKER uses only JOURNAL's closed phrase sets, including `proposal withheld`,
and builds refs only with `make_ref(kind, data, None)`. Reservation and writer
are Linux-only (`liveness_unsupported` elsewhere), as is `pidfd_open`.

## 9. Deferred pinned obligations

WORKER's receipt lists, as `upstream_phase_unmet` with owner CLOSEOUT, every
row of `plans/evidence/supervised-worker/SCHEMA.md` whose `owner` names WORKER.
Rows are listed by section and id, from `coverage_inventory`,
`semantic_cases` and `semantic_inventory`. The receipt test derives that set
from the SCHEMA receipt and requires equality. Exit codes, lifecycle enums,
termination fields and the result/evidence labels are likewise deferred to
CLOSEOUT's public reconciliation. CLOSEOUT's `caller_context` echo cases are
falsified at the `caller_context_sha256` site (§3.1 step 2, W15).
