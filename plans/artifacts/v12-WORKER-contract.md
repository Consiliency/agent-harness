# v12 WORKER frozen contract (IF-0-WORKER-1)

Planning input for `plans/phase-plan-v12-WORKER.md`, sealed by that plan's
`plans/manifest.json` `frozen_inputs` entry. It is read-only during execution; a
needed change is an artifact amendment with a new seal, never a lane decision.

Everything here is a harness-local Python/CLI surface. It is not a public wire
type and asserts nothing about unpublished schemas. Field names follow the
roadmap vocabulary and the vendored v1 run-status labels (IF-0-SCHEMA-1) as
provisional fixture labels; CLOSEOUT's v2 reconciliation supersedes them by
amendment. The roadmap's EC-WORKER-1..4 remain the only acceptance authority;
this file never restates them.

## 1. Consumed interfaces

Pre-existing, landed, and not edited by WORKER:

- `supervised_launch` (IF-0-ENVELOPE-1 as landed): `prepare_launch(envelope_bytes,
  *, validator, decoder, config) -> PreparedLaunch | Refused`,
  `consume_admission(prepared) -> LaunchInputs | Refused`, `classify_workspace(
  workspace, target, tier) -> (kind, device, inode)`, `LaunchInputs`,
  `LaunchConfig`, `EnvelopeView`, `ExecutableIdentity`, `Refused`, `sha256`.
- `supervised_dependency.preflight_supervised_route(command) -> Refused | None`
  with keys `supervised-launch`, `supervised-status`, `supervised-cancel`.
- `supervised_launch_binding.load_validator_binding` (not called by the WORKER
  CLI; see §6).
- `convergence/adapters/base.py`: `run_bounded`, `AdapterExecutionRequest`,
  `_child_environment`; `codex.py`: `run_codex_adapter`.
- `output_retention.mark(root, run, state, *, owner_pid=None)` and
  `output_retention.prune(root, *, days=None, apply=False, now=None)`.
- `panel_invoker.launch_owned` with `SeatLaunchRole.EXECUTOR_TRUSTED`.
- IF-0-JOURNAL-1 as the roadmap freezes it, plus the §8 requirements.

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
  restarted. Expiry: `timed_out`/`harness`/`SIGKILL`. `cancel` set:
  `cancelled`/`operator`/`SIGKILL`. Natural leader exit: `completed`/`worker`
  with `exit_code`, followed by reclaiming the group. A spawn `OSError` returns
  `failed_to_start`/`harness` with `spawn_count == 1`.
- Both pipes drain to EOF. Every byte of stdout and stderr is digested and
  counted. Only stdout bytes up to `proposal_cap` are retained; past the cap,
  draining and digesting continue and `proposal_overflow` is set. stderr bytes
  are never retained. Neither stream is decoded or copied into any record.
- `stdin` is written once through the same selector loop, then closed. An EPIPE
  ends delivery and sets `stdin_delivered=False`. Instructions never enter argv.
- `worker_child_environment(allow)` takes `_child_environment()`, removes
  `WORKER_ENV_DROP` and the prefixed names, then keeps only names in `allow`
  plus the scratch-relocation names `child_scratch_env` adds. Records carry
  variable names only, never values or value digests.
- `run_bounded`, `AdapterExecutionRequest` and `run_codex_adapter` keep their
  signatures, statuses, fixed details, 64 KiB cap, DEVNULL stdin, basename
  check and review isolation byte-for-byte in behavior. Sharing internals is
  allowed only behind parity tests.
- A `setsid` descendant can leave the group. `BoundedCapture` makes no claim
  about descendants outside the launcher's own process group.

## 3. Patch-return adapter and lifecycle — `patch_return.py`, `codex.py` (SL-1)

```python
@dataclass(frozen=True)
class WorkerSettings:            # parsed from the config bytes whose sha256 == LaunchInputs.config_digest
    proposal_cap: int            # key "worker_proposal_cap", 1..PROPOSAL_CAP_MAX, default PROPOSAL_CAP_MAX
    audit_entry_cap: int         # key "worker_audit_entry_cap"
    audit_byte_cap: int          # key "worker_audit_byte_cap"
    cancel_wait_seconds: int     # key "worker_cancel_wait_seconds"
    environment_allow: frozenset[str]   # key "worker_environment_allow"
    retention_days: int | None   # key "worker_retention_days"

@dataclass(frozen=True)
class WorkerAttemptIdentity:
    assignment_digest: str; envelope_digest: str; launch_digest: str; raw_digest: str
    run_id: str; attempt_id: str
    target_unit_ids: tuple[str, ...]; readonly_neighbor_unit_ids: tuple[str, ...]
    snapshot_reference: str; caller_context_digest: str

@dataclass(frozen=True)
class BaselineIdentity:
    path: str; git_blob_sha1: str | None; sha256: str | None

@dataclass(frozen=True)
class ProposalReturn:
    status: str                  # see §3.2
    proposal_bytes_digest: str | None
    byte_length: int
    baselines: tuple[BaselineIdentity, ...]
    locator: str | None          # evidence-root-relative; never authority

@dataclass(frozen=True)
class JournalAnchor:
    terminal_seq: int; chain_head_sha256: str

@dataclass(frozen=True)
class WorkerResult:
    identity: WorkerAttemptIdentity | None   # None only before consume_admission succeeds
    state: str                   # finished | refused
    termination: object | None   # JOURNAL's termination record (reason, signal, by), passed through unchanged
    refusal: str | None
    worker_invocations: int
    proposal: ProposalReturn | None
    evidence_envelope_digest: str | None
    journal_anchor: JournalAnchor | None

CancelOutcome = Literal["cancelled", "already_terminal", "cancel_pending",
                        "unknown_attempt", "owner_unverified", "owner_not_live"]

def default_state_root() -> Path: ...
def run_patch_return(prepared: PreparedLaunch, *, config: LaunchConfig,
                     state_root: Path, cancel: threading.Event | None = None) -> WorkerResult: ...
def cancel_attempt(*, state_root: Path, run_id: str | None = None,
                   attempt_id: str | None = None,
                   launcher_commands: tuple[tuple[str, ...], ...] = PRODUCTION_LAUNCHER_COMMANDS
                   ) -> CancelOutcome: ...
# codex.py
def run_codex_patch_return(prepared: PreparedLaunch, *, config: LaunchConfig,
                           state_root: Path, cancel: threading.Event | None = None) -> WorkerResult: ...
```

`run_codex_patch_return` refuses `provider_mismatch` with zero effects unless
`Path(LaunchInputs.executable.path).name == "codex"`, then delegates. The
generic `run_patch_return` is provider-neutral: executable identity comes from
admission digests, not basenames.

### 3.1 Order (each step's refusal has zero later effects)

1. `consume_admission(prepared)`. On `Refused`: return `state=refused`, nothing
   reserved, no journal/evidence/launcher effects.
2. Re-read the config file and require `sha256 == LaunchInputs.config_digest`
   (`config_changed`); parse `WorkerSettings` (`worker_settings_invalid`).
   Require `state_root` outside workspace, target and reference roots, with
   operator uid and 0700 (`state_root_unsafe`). Still zero effects.
3. Durable JOURNAL reservation of (assignment_digest, run_id, attempt_id). A
   failure, a duplicate, a terminal or a crash-reserved id refuses with zero
   invocations and no further effects. The launcher then journals the first
   state line, `queued`. If that write fails, the attempt stays reserved with no
   terminal, is never reused, and JOURNAL reports it unknown. From here every
   refusal journals terminal `refused` from `queued` with
   `worker_invocations == 0`.
4. Launcher record (§5) and evidence directory created; `mark(evidence_root,
   run, "active", owner_pid=os.getpid())` before any evidence byte is written.
5. Before-audit (§3.3). An error refuses `audit_error`.
6. Inside `before_spawn`: if `cancel` is set, refuse `cancelled_before_start`.
   Recheck `classify_workspace` kind/device/inode and the full-file sha256 of
   the executable and each wrapper through component-wise O_NOFOLLOW reads.
   Mismatches refuse `workspace_changed`, `device_changed`, `inode_changed`,
   `executable_changed` or `wrapper_changed`. Then journal `running` as the
   last action; journaling failure refuses `journal_unavailable`.
7. `run_bounded_capture`. From the spawn call onward, every outcome is
   `finished` with the capture's termination; refusal never follows start.
8. After-audit and comparison (§3.3), proposal decision (§3.2).
9. Write `proposal.bin` (only when `returned`) and `evidence.json` (§4), both
   0600, fsync, then `mark(..., "sealed")` after every writer has stopped.
10. Journal the terminal line with `result_binding = {envelope_digest, run_id,
    attempt_id, proposal_bytes_digest | null, evidence_envelope_digest}`, and
    take the `JournalAnchor` from JOURNAL's return value.
11. Best-effort `prune(evidence_root, days=retention_days, apply=True)`. Its
    failure never alters the result.

Descriptor execution (ELF through an inherited fd path) is used where
supported. Otherwise evidence records `exec_binding: "path_recheck"` and
readiness discloses the remaining check-to-exec window.

### 3.2 Proposal decision (first matching rule wins)

| Condition | `status` |
| --- | --- |
| termination is not `completed`, or exit_code != 0 | `withheld_incomplete` |
| `proposal_overflow` | `withheld_oversized` |
| either audit errored | `withheld_audit_error` |
| an unexplained change | `withheld_unexplained_change` |
| stdout empty | `absent` |
| structural check fails | `withheld_malformed` |
| otherwise | `returned` |

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

The audit runs in process. It never executes git or reads git configuration.
A snapshot is the sorted list of (relative path, type ∈ {file, dir, symlink},
permission bits, size, file sha256 or link target) for:

- (a) the workspace tree;
- (b) the protected target tree;
- (c) the target's `HEAD`, `packed-refs` and `refs/**`, read from the git
  directory physically inside the target. A gitfile pointing elsewhere is an
  audit error.

Walks use dir_fd and O_NOFOLLOW. Other file types, unreadable entries and
exceeding `audit_entry_cap`/`audit_byte_cap` are audit errors. `.git/objects/**`
is excluded by name in both trees. This disclosed limitation means object-store
additions are not audited; refs are.

## 4. Evidence envelope, result record and layout

State root: `default_state_root()` is `<pw_dir>/.local/state/agent-harness/
supervised-worker`, with `pw_dir` taken from `pwd.getpwuid(os.geteuid())`, never
from `$HOME`. Tests pass `state_root` in process only. Layout (dirs 0700, files 0600):

- `<state_root>/journal/` — JOURNAL-owned (§8, J6); outside every prune root.
- `<state_root>/launchers/<run>.json` — launcher records (§5).
- `<state_root>/evidence/` — the only `output_retention` root. One run directory
  per attempt, named `a-` + the first 32 hex digits of
  sha256(assignment_digest `\0` run_id `\0` attempt_id). It holds `evidence.json`
  and optional `proposal.bin`.

`evidence.json` is a local, metadata-only record labelled
`"local_record": "agent-harness.supervised-worker.evidence", "version": 0,
"fixture_labelled": true`. It holds:

- `WorkerAttemptIdentity`;
- `argv` (prompt-free by construction) and `instruction_digest`;
- executable `{realpath, sha256, version}` and wrappers `[{realpath, sha256}]`.
  `version` comes from the config's held `qualified_version`; no probe is run.
  It is null with `version_source: "unqualified"` for the audit tier;
- config, template and qualification digests;
- workspace kind, device and inode, and the tier;
- `environment_names`, `exec_binding`;
- termination, `exit_code`, `worker_invocations`;
- stdout and stderr `StreamDigest`s, `duration_ns`, `stdin_delivered`;
- the `ProposalReturn`, `audit {status, before_sha256, after_sha256,
  workspace_writes_detected, unexplained_count}`;
- `retention_state`.

`evidence_envelope_digest` is the sha256 of its exact bytes. No prompt,
instruction, stdout, stderr, proposal content, environment value, secret or
caller_context content appears. caller_context appears by digest only.

The `--result` record carries the same label pattern
(`agent-harness.supervised-worker.result`, version 0). It is `WorkerResult`
serialized, including `journal_anchor` as the controller-held anchor.

## 5. Native cancel and launcher identity

The launcher:

1. takes its nonce from the attempt's journal writer identity: the random
   `writer_instance_id` (at least 128 bits) of the writer bound at
   reservation (J3);
2. at step 4 creates `launchers/<run>.json` with O_CREAT|O_EXCL|O_NOFOLLOW, mode
   0600, holding {run_id, attempt_id, assignment_digest, pid,
   process_start_time (encoded exactly as the journal writer identity encodes
   it), exe_realpath, exe_sha256, cmdline_sha256, nonce};
3. holds an exclusive POSIX `fcntl` lock on that file for its lifetime.

The nonce therefore exists in two places written by the launcher: the 0600
record and its own journal writer identity. A forger must both write a
matching record and hold its lock as the named live process.

`SIGTERM` sets the launcher's cancel event. Before spawn this refuses
`cancelled_before_start`. While running, the launcher journals `cancelling`,
then the capture kills only its own group. A cancel arriving between
reservation and record creation finds no record and returns `owner_unverified`.

`cancel_attempt` resolves the target through JOURNAL's read API (J4). `--run`
uses JOURNAL's latest-attempt order, and ambiguity gives `unknown_attempt`. The
journal outcomes are:

- terminal: `already_terminal`;
- non-terminal with a dead owner: `owner_not_live` (zero signals);
- otherwise, verification proceeds as follows.

Verification checks, all required, zero signals on any failure
(`owner_unverified`):

1. the record has operator uid, 0600 mode, a no-follow path and a well-formed
   body;
2. the journal writer identity (owner_pid, process_start_time,
   writer_instance_id) equals the record's (pid, process_start_time, nonce);
3. `pidfd_open(pid)` succeeds; this pidfd is the only signal target;
4. the live process start identity, computed by the same function JOURNAL
   uses for its writer identity, equals the record;
5. `/proc/<pid>/exe` realpath equals the record and the canceller's own
   interpreter realpath;
6. sha256 of the live cmdline equals the record, and that cmdline follows the
   interpreter with one entry of `launcher_commands`;
7. the record lock holder (`F_GETLK` `l_pid`) equals pid.

Then `pidfd_send_signal(SIGTERM)` and wait up to `cancel_wait_seconds` for a
terminal line: `cancelled` if it shows reason `cancelled`, `already_terminal`
if another terminal won, or `cancel_pending`. Repeats are idempotent: they
re-verify and re-signal. A journal-supplied pgid is never signalled.

`PRODUCTION_LAUNCHER_COMMANDS = (("-I", "-m", "phase_loop_runtime.supervised_worker_cli",
"launch"),)`. The CLI always passes this constant. Only in-process tests may
pass a fixture launcher command; no CLI flag, environment or config can.

## 6. CLI — `supervised_worker_cli.py` (SL-2)

`python -I -m phase_loop_runtime.supervised_worker_cli` with
`main(argv: Sequence[str] | None = None) -> int` and exactly these verbs:

- `launch --envelope <path> --result <path>`;
- `status (--run <id> | --attempt <id>)`;
- `cancel (--run <id> | --attempt <id>)`.

Unknown verbs or flags refuse. It refuses unless `sys.flags.isolated`, and
imports only stdlib and `phase_loop_runtime`. It does not replace
`phase-loop status`, adds no console script and no `pyproject.toml` change.

- Every verb first calls `preflight_supervised_route` with its key, before any
  file, import-binding, journal, evidence or output effect.
- `launch` then resolves `_production_codec()`. In WORKER it is `None`, so the
  verb refuses `codec_unavailable`, with zero envelope reads, binding loads,
  probes, spawns, journal, evidence or result writes. CLOSEOUT SL-1 replaces
  `_production_codec` with the pinned public codec binding (trust checks as for
  validator bindings) and wires the remaining launch steps. WORKER freezes and
  tests the following building blocks in process:
  - `read_envelope_file(path: Path, *, cap: int) -> tuple[bytes, int] | Refused`
    returns (bytes, st_mode). It requires operator uid, a regular file,
    component-wise O_NOFOLLOW and the cap, and refuses group/world write. After
    decode, any inline instruction member read from a group/world-readable file
    refuses `envelope_mode_unsafe`.
  - `open_result_file(path: Path, *, excluded: tuple[Path, ...]) -> int | Refused`
    requires an absolute path with a verified 0700 operator parent opened by
    dir_fd. It opens O_CREAT|O_EXCL|O_NOFOLLOW with mode 0600, outside the
    workspace, target, reference roots and state root.
- `status` is provider-free. It prints JOURNAL's bounded page for the run or
  attempt, with display text only from JOURNAL's closed phrase set.
- `cancel` prints the `CancelOutcome`.
- Exit codes are provisional fixture labels and not part of IF-0-WORKER-1:
  0 for a written record, 2 for usage, 10 for refusal, 20 for an uncertain
  outcome. Consumers read records, not exit codes.

## 7. Test and mutation obligations

Path-entered tests use real offline subprocesses (synthetic provider scripts in
`tests/fixtures/supervised_worker_local/`, labelled non-authoritative) and the
real landed JOURNAL writer. No live provider, credential or network is used.
Isolated-Python children insert the checkout's absolute source root and assert
`phase_loop_runtime.__file__` lies beneath it (ENVELOPE rule). Mode-checking
tests pin umask 077 and restore it.

| ID | Lane | Obligation | EC |
| --- | --- | --- | --- |
| W1 | SL-0 | Capture: stdout/stderr digests over all bytes, cap + overflow, stdin one-shot and not in argv, deadline, cancel, group reclaim, failed start, `before_spawn` refusal = zero spawns | EC-WORKER-1, EC-WORKER-4 |
| W2 | SL-0 | `run_bounded` parity: every existing status/detail/bound unchanged | EC-WORKER-1 |
| W3 | SL-0 | Planted `SSH_AUTH_SOCK`, `GIT_ASKPASS`, `SSH_ASKPASS`, `GIT_CONFIG_*` credential-helper, vendor and GH tokens absent from the child; allowlist narrows | EC-WORKER-4 |
| W4 | SL-1 | Order §3.1: zero invocations and zero effects for every pre-reservation refusal; post-reservation refusals journal `refused` from `queued` | EC-WORKER-2, EC-WORKER-4 |
| W5 | SL-1 | Replay one envelope sequentially, concurrently across 4 processes, and after a crash between reservation and spawn: at most one spawn in total | EC-WORKER-2, EC-WORKER-4 |
| W6 | SL-1 | Pre-spawn recheck of each identity element | EC-WORKER-2 |
| W7 | SL-1 | Proposal decision table, every row; baselines; malformed and oversized | EC-WORKER-1, EC-WORKER-4 |
| W8 | SL-1 | Audit: workspace change per tier, target change, ref change, gitfile escape, cap and special-file errors | EC-WORKER-1, EC-WORKER-4 |
| W9 | SL-1 | Evidence binding fields of §4; prompt, stdout and stderr sentinels absent from journal, evidence and result | EC-WORKER-2, EC-WORKER-4 |
| W10 | SL-1 | Cancel: real launcher race (queued, running, terminal), idempotent repeat, forged record naming an unrelated same-user process (zero signals), stale owner, pid reuse | EC-WORKER-3, EC-WORKER-4 |
| W11 | SL-1 | setsid descendant escapes, recorded as the limitation; the test reaps its own escapee | EC-WORKER-3, EC-WORKER-4 |
| W12 | SL-1 | Retention: active before writes, sealed after writers, prune leaves the journal intact, JOURNAL page shows `retention_dropped` with digests kept; retry = fresh admission + new attempt, evidence preserved | EC-WORKER-3, EC-WORKER-4 |
| W13 | SL-2 | Installed isolated CLI: `codec_unavailable` with zero probes and effects; required sessions refuse launch/cancel before reads; shadowed stdlib and validator modules in the workspace cwd do not load; envelope owner/mode/symlink/size; result O_EXCL/0600/no-follow/outside roots; CLI cancel rejects a fixture launcher | EC-WORKER-2, EC-WORKER-4 |
| W14 | SL-2 | Receipt validation against producer results, deferred-obligation list (§9) and source bindings | EC-WORKER-4 |

Mutation controls: each production guard named below gets a source-copy mutant
in its lane's own test file. The mutant must turn a previously passing
path-entered assertion red. Mutating a test-side oracle never counts.

- SL-0: proposal cap, stderr digest, deadline arm, cancel kill, killpg reclaim,
  stdin channel, each drop name/prefix, allowlist, `before_spawn` gate.
- SL-1: consume-before-reserve, reservation-before-spawn,
  reservation-failure gate, each §3.1 step-6 recheck, running-before-spawn,
  each §3.2 row, each §3.3 scope, evidence field binding, active-before-write,
  seal-after-writers, each §5 verification check, pidfd target, provider
  basename (codex).
- SL-2: isolated flag, preflight-before-read, codec gate, each envelope-file
  check, each result-open flag.

## 8. JOURNAL requirements beyond the roadmap freeze

The roadmap freezes only "durable journal, replay projection and bounded read
API" plus EC-JOURNAL-1..4. WORKER additionally needs the following; each is a
cross-phase dependency to reconcile with JOURNAL's landed API before WORKER
execution:

- J1 — One call atomically reserves (assignment_digest, run_id, attempt_id)
  under the per-assignment lock. It returns a writer handle bound to that
  attempt, or a typed refusal (duplicate, terminal, crash-reserved,
  unavailable).
- J2 — The handle appends `state` (running, cancelling), `event` (closed phrase
  plus refs) and `terminal` (finished or refused with termination, refusal,
  worker_invocations, result_binding). The terminal append returns the line's
  seq and the chain-head sha256.
- J3 — The writer identity bound at reservation is returned to the caller
  before any spawn: a random `writer_instance_id` of at least 128 bits, and
  the calling launcher's owner pid and process start time. The function that
  computes the process start identity is importable, so cancel can recompute
  it for a live pid. Events use only JOURNAL's closed phrase set; WORKER adds
  no phrase without a JOURNAL amendment.
- J4 — A bounded read by run or by attempt returns projection state, terminal
  record and writer identity, with latest-attempt resolution by the admission
  index.
- J5 — Pages disclose `retention_dropped` for an evidence reference whose
  directory a caller-supplied resolver reports absent, keeping digests.
- J6 — The journal root is caller-supplied (WORKER passes `<state_root>/journal`)
  and sits outside every output_retention root.

## 9. Deferred pinned obligations

WORKER's receipt lists, as `upstream_phase_unmet` with owner CLOSEOUT, every
row of `plans/evidence/supervised-worker/SCHEMA.md` whose `owner` names WORKER.
Rows are listed by section and id, from `coverage_inventory`,
`semantic_cases` and `semantic_inventory`. The receipt test derives that set
from the SCHEMA receipt and requires equality. Exit codes, lifecycle enums,
termination fields and the result/evidence labels are likewise deferred to
CLOSEOUT's public reconciliation.
