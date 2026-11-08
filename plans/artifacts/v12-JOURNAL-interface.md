# JOURNAL frozen interface (IF-0-JOURNAL-1)

Planning artifact for `plans/phase-plan-v12-JOURNAL.md` (agent-harness#1818).
This is a harness-local seam contract, not a public wire schema. The plan's
manifest entry seals this file by SHA-256 under `frozen_inputs`; a change needs a
reviewed plan amendment and a reseal. Roadmap EC IDs remain the only acceptance
authority. This file restates no EC text. Revision 2 applies the 2026-11-08
advisor-board edits on agent-harness#1925 and the owner rulings recorded in the plan.

## 1. Inputs and validation boundary

Recorded 2026-11-08 by hashing the vendored files and fetching the same paths
from public Consiliency/consiliency-contract at both pinned commits:

| Resource (vendored under `schemas/supervised-worker-v1/`) | SHA-256 | v1 pin `93db4b4f…` | v2 pin `2b91ef85…` |
| --- | --- | --- | --- |
| `run-status.schema.json` | `5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30` | identical | identical |
| `conformance/run-status.vectors.json` | `5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730` | identical | identical |

The run-status family therefore has one byte-identical public definition across
the SCHEMA intake, the CLOSEOUT intake and the v13 `x-contract-pins.run_status`
pin. JOURNAL implements against its enums, required fields, bounds,
`x-journal-rules`, `x-semantic-rules` and `x-canonicalization`. The publisher
status stays `provisional`. CLOSEOUT still discharges authoritative acceptance
(roadmap Execution Notes); JOURNAL's vector runs are early reconciliation evidence.

**Validation boundary (owner ruling).**

- Production modules `run_status.py` and `run_status_projection.py` never import
  `supervised_contracts` (the contract-intake module). They also never contain a
  string constant naming it, docstrings included. The landed
  `test_supervised_contracts_receipt.py::test_runtime_consumers_remain_independent`
  scans every runtime module for both, and CLOSEOUT's allowlist does not cover
  `run_status*`.
- Production validates structure with the stdlib plus `rfc8785`, using a closed
  checker for the five public definitions (`journal_line`, `projection`,
  `page_request`, `page`, `reader_view`). It checks required keys,
  `additionalProperties: false`, types, enums, consts, 64-hex patterns and length
  bounds.
- Tests own the pinned-schema cross-check. They load the bundle and call
  `validate_record`, and they assert three things:
  - the checker's key, enum and bound tables equal the tables read from the
    pinned schema;
  - every vector record and every produced record gets the same accept/reject
    verdict from both validators;
  - the landed independence test stays green.

Harness-local additions (sections 3, 5 and 7) are labelled local. They never
enter a public record, and the admission index uses its own schema name.

## 2. Storage layout, root and trust checks

```text
<root>/                                  0700, owner = euid
  attempts/                              0700
    <attempt_id>/                        0700, created O_EXCL by reserve_attempt (global claim)
      lock                               0600, held LOCK_EX by the single writer for its lifetime
      0000.jsonl, 0001.jsonl, …          0600 segments; 4-digit decimal index, contiguous from 0000
  assignments/                           0700
    <assignment_digest>/                 0700
      lock                               0600, per-assignment reservation lock
      index.jsonl                        0600, append-only admission index
  runs/                                  0700
    <run_id>                             0600, created O_EXCL; exactly "<assignment_digest>\n"
```

- **Root (owner ruling).** `default_journal_root()` takes no arguments. It
  returns `<pw_dir>/.local/state/agent-harness/supervised-worker/journal`, where
  `pw_dir` comes from `pwd.getpwuid(os.geteuid())`. It never reads `$HOME`,
  `$XDG_STATE_HOME` or any other environment variable. The path equals WORKER's
  `<state_root>/journal` for its default state root, so every tool finds one
  fixed per-user journal. `open_journal_root` also accepts an explicit absolute
  root, but only from in-process tests or trusted operator configuration, never
  from the environment or an untrusted argument.
- `open_journal_root(path, *, create, excluded)` refuses `journal_root_unsafe`
  for:
  - a relative path or any symlink component;
  - a root equal to, inside, or containing an `excluded` root (WORKER passes
    workspace, target and envelope-referenced roots);
  - a wrong owner or mode.

  With `create=True` it creates, in order, each missing component below an
  existing verified parent and then `attempts/`, `assignments/` and `runs/`. Each
  is created with `mkdir` 0700 and an explicit `fchmod` (umask has no effect),
  then the new directory's parent is fsynced before the call returns.
- Every later open is `dir_fd`-relative with `O_NOFOLLOW` at each component.
  `fstat` must show `st_uid == geteuid()`. Directories need exact mode 0700.
  Files need exact mode 0600, `S_ISREG` and `st_nlink == 1`. A violation is
  `journal_path_unsafe`: readers report it as a diagnostic (display `unknown`),
  and writers and reservations refuse.
- Readers open `O_RDONLY`. They never create, truncate, rename, unlink, chmod or
  lock-break. Only `open_journal_root(create=True)`, `reserve_attempt` and
  `AttemptWriter` write, and only by appending or exclusive creation.
- No listener, watch, inotify or polling loop exists. Every read is one bounded pass.
- **Platform (owner ruling).** The supervised worker and journal writer are
  Linux-only in v12, because process start identity comes from `/proc`
  (section 4). Elsewhere, reservation and writer open refuse
  `liveness_unsupported`. Readers still work.
- Same-login processes can forge a self-consistent chain or index. Writer binding
  is not authentication against them, and readiness documentation must say so.

## 3. Identifier grammar (local)

`run_id` and `attempt_id` must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. They
must not be `.` or `..`, and must be valid single path components. The
128-character ceiling is the public run-status `maxLength`. Longer ids are refused
and never truncated. `assignment_digest`, `envelope_digest`, `snapshot_ref`,
`launch_digest` and `caller_context_sha256` must be lowercase 64-hex. A violation
refuses `identifier_invalid` before any filesystem effect.

## 4. Journal line format and writer-only rules

- Lines are the public `journal_line` definition, exactly: `schema`
  (`supervised_run_status.v1`), `version` (`"1"`), `line_kind`, `seq`, `attempt`,
  `units`, `writer`, `observed_at`, `redaction_posture`
  (`digests_and_repo_relative_locators_only`) and `body`.
- Each object line is RFC 8785 (JCS) bytes from the existing `rfc8785`
  dependency, followed by one LF. Segment SHA-256 follows the schema's
  `x-canonicalization` over the on-disk bytes. No dependency or lock change is
  needed.
- `seq` starts at 0 for the segment-0 header and is gapless across segments.
  Each segment begins with a `header` line. Segment 0 carries
  `previous_segment_sha256: null` and `previous_last_seq: null`. Segment *n*
  carries the SHA-256 of segment *n-1* and its last seq.
- **Writer identity is minted once, in `reserve_attempt`:**
  - `harness_id` is `"phase-loop-runtime"`; `harness_version` is
    `phase_loop_runtime.__version__`;
  - `writer_instance_id` is 128-bit random lowercase hex;
  - `owner_pid` is `os.getpid()`;
  - `process_start_time` is `process_start_identity(pid)`, which returns
    `linux-proc:<boot_id>:<starttime clock ticks>` from
    `/proc/sys/kernel/random/boot_id` and `/proc/<pid>/stat` field 22, with no
    wall-clock conversion.

  The identity is recorded in the index entry and returned as
  `Reservation.writer`. `open_writer` copies `Reservation.writer` unchanged into
  every line it writes and never mints a second id. It refuses
  `writer_identity_mismatch` unless the current process has the same `owner_pid`
  and `process_start_time`.
- `observed_at` is an informational UTC timestamp and never orders anything.
- Every string is at most 512 characters. Event `message` is
  `{label: "untrusted_display_text", text: <phrase>}`. `refs` carry
  `{kind, sha256, locator}`, built only by `make_ref`. The locator is null or
  repository-relative: non-empty, not absolute, no `..` segment, no backslash.
- **Scope of writer-only rules.** The writer-format rules above (`harness_id`,
  hex `writer_instance_id`, the `linux-proc:` encoding) and the phrase set in
  section 9 bind only `AttemptWriter` output and the display layer. Readers
  never enforce them. A reader accepts any schema-valid writer strings and any
  event text the public rules allow (at most 200 characters, no line break or
  control character). The control vectors use `writer-1`, ISO start times and
  messages outside section 9, and must read with no diagnostics. Liveness
  compares the recorded `process_start_time` with the observer's value by exact
  string equality, whatever its format.

## 5. Admission index and reservation (local)

An index entry is one JCS line + LF:

```text
{schema: "phase_loop.supervised_admission_index.v1", version: "1", index_seq,
 previous_entry_sha256 (null for index_seq 0), assignment_digest, envelope_digest,
 run_id, attempt_id, launch_digest, caller_context_sha256, units, writer}
```

`reserve_attempt` runs these steps in order. Every file it creates gets an
explicit `fchmod` and is verified (section 2).

0. Validate identifiers and digests, then mint the writer identity (section 4).
   `liveness_unsupported` refuses here. There are no effects yet.
1. If `assignments/<digest>` is absent, `mkdir` it 0700, `fchmod` it and fsync
   `assignments/`. Then open it verified.
2. Open `lock` with `O_CREAT|O_NOFOLLOW` 0600. If the file was created, fsync the
   assignment directory. Take `LOCK_EX`. Steps 3–7 run under this lock.
3. Read and verify the whole index: chain digests, gapless `index_seq`,
   schema/version, a per-entry assignment digest equal to the directory key, no
   torn tail, size within limits. Any defect refuses `index_unverifiable`. The
   index is never repaired.
4. An `attempt_id` already in the index refuses `attempt_reserved`.
5. **Run claim.**
   - If `runs/<run_id>` exists, read it verified and bounded. Exactly
     `<assignment_digest>\n` for this assignment proceeds. Another digest refuses
     `run_assignment_mismatch`. An empty, short, malformed or unsafe record
     refuses `run_record_unreadable`.
   - If it is absent, create it with `O_CREAT|O_EXCL|O_NOFOLLOW` 0600, write the
     record fully, fsync the file, then fsync `runs/`. EEXIST falls back to the
     existing-record check.
6. `mkdir attempts/<attempt_id>` with O_EXCL and 0700, `fchmod` it and fsync
   `attempts/`. EEXIST refuses `attempt_reserved`. This covers ids used by
   another assignment and ids from a reservation that crashed before step 7.
7. Append the entry with `O_APPEND` and a full-write loop, then fsync the index
   file. If the file was created, also fsync the assignment directory.
8. Release the lock and return `Reservation(identity, units, index_seq,
   entry_sha256, writer)`.

**Crash windows.**

- A crash after step 1 or 2 leaves an empty assignment, which is harmless.
- A crash inside step 5 may leave an empty or short run record. That run id then
  refuses `run_record_unreadable` until operator quarantine.
- A crash after step 5 leaves a valid run claim with no attempt, which is
  harmless.
- A crash after step 6 means the attempt id can never be reused, and readers
  report it `attempt_unindexed` (display `unknown`).
- A torn index tail makes the assignment `index_unverifiable` for readers and
  reservations alike.

**Recovery (owner ruling).** v12 recovery is manual operator quarantine. Rename
the affected assignment directory or run record aside within the root and keep
its bytes. Every attempt and run id it held stays claimed through `attempts/` and
`runs/`. A sealed recovery record is deferred to a later phase.

`caller_context` enters only as `caller_context_sha256`: the SHA-256 of the
RFC 8785 bytes of the exact admitted value, computed by the caller. JOURNAL checks
only that it is 64-hex and never receives the value.

`resolve_run(root, run_id)` behaves as follows:

- an invalid id refuses `identifier_invalid`;
- an absent run record returns `()`;
- an unreadable record refuses `run_record_unreadable`;
- an unverifiable index refuses `index_unverifiable`;
- otherwise it returns the attempt ids whose index entries name that run, in
  index order. This may be `()` after a crash between steps 5 and 7.

## 6. Writer

`open_writer` takes `LOCK_EX | LOCK_NB` on `attempts/<attempt_id>/lock`. It
creates the lock with `O_CREAT|O_EXCL` 0600 and fsyncs the attempt directory. A
busy lock refuses `journal_writer_busy`. Any existing segment refuses
`journal_exists`, so a writer is never resumed. It creates `0000.jsonl` with
O_EXCL and writes the header.

Every append is a full write followed by an fsync of the file, plus the
directory when a file was created. Each append returns the new `ChainHead`.

**Poisoning.** Any `OSError`, short write or fsync failure during an append or
rotation poisons the writer. After that, every `state`, `event` and `terminal`
call refuses `writer_poisoned` and writes nothing, and `close()` only releases
the lock. A partially written line stays on disk, where readers report
`journal_torn_line`.

**Lifecycle.** The lifecycle is the schema's `x-journal-rules.lifecycle`,
enforced before any byte is written:

- The first state line must be `queued`.
- `finished` requires `termination`.
- `refused` requires `refusal`, `worker_invocations == 0` and no earlier
  `running`.
- `worker_invocations` never decreases.
- Nothing follows a terminal line.
- Event text must be a section 9 phrase.

A violation refuses `lifecycle_invalid` (or `phrase_invalid`) and writes nothing.

**Rotation.** Rotation happens before an append that would exceed
`segment_max_lines` or `segment_max_bytes`. The new segment is created O_EXCL
with its chained header, then the file and the attempt directory are fsynced.

**Line cap.** `per_attempt_line_cap` counts every line of the attempt across all
segments, headers included. This is the provisional reading of the public
`per_attempt_event_cap`, reconciled by CLOSEOUT. A non-terminal append, together
with any rotation header it causes, may not bring the total above cap − 2. The
last two slots are reserved for a possible rotation header and the terminal
line, so a terminal always fits whatever the rotation state. A refused append
returns `event_cap_reached`.

| Limit | Default | Source |
| --- | --- | --- |
| `per_attempt_line_cap` | 10000 lines, headers included, last 2 reserved | public `per_attempt_event_cap` |
| `event_message_max_chars` | 200 | public |
| `segment_max_lines` / `segment_max_bytes` | 1000 / 1 MiB | local |
| `read_segment_max_bytes` | 4 MiB | local |
| `index_max_entries` | 100000 | local |

## 7. Reader rules and diagnostics

`read_attempt` and `read_index` make one bounded pass. Segments are ordered by
parsed integer index, never by mtime, wall clock or directory order. Readers
apply only the structural checker, the public `x-semantic-rules` and the local
codes below, never the writer-only rules in section 4. Diagnostic sets are exact
and unordered. For the 19 `kind=journal` vectors, the production reader must
return exactly `expected`, and every vector `expected_effect.display` value must
match.

Public codes (`x-semantic-rules`) are used unchanged: `journal_torn_line`,
`journal_malformed_line`, `journal_unknown_version`, `journal_foreign_writer`,
`attempt_overwritten`, `attempt_provenance_mismatch`, `attempt_evidence_copied`,
`refused_after_launch`, `lifecycle_invalid`, `raw_output_in_record`,
`locator_not_repo_relative`, `projection_behind_journal`,
`projection_not_from_journal`, `owner_not_live`, `run_record_foreign`,
`runtime_not_work_outcome` and `read_unbounded`.

Local codes never appear in a public record:

| Code | Meaning | Display |
| --- | --- | --- |
| `journal_missing` | attempt directory or segment 0000 absent | unknown |
| `journal_unexpected_entry` | an entry other than `lock` and `NNNN.jsonl` | unknown |
| `journal_path_unsafe` | owner, mode, link, type or nlink check failed | unknown |
| `journal_oversize` | a segment or line count over a read cap | unknown |
| `attempt_unindexed` | an attempt directory with no index entry | unknown |
| `index_unverifiable` | index chain, sequence, schema, key, torn tail or size defect | unknown |
| `run_record_unreadable` | run record empty, short, malformed or unsafe (refusal, from `resolve_run` and `reserve_attempt`) | — |

These checks produce `attempt_provenance_mismatch`:

- each line's `attempt` against the header and against the directory name;
- the header against its index entry;
- the index entry against its assignment directory;
- the terminal `result_binding` against the line's identity.

An index-entry writer that differs from the header writer is
`journal_foreign_writer`. `attempt_evidence_copied` compares evidence-envelope
digests across the attempts of one assignment, in index order. Any diagnostic
sets display `unknown`. Readers never repair or truncate.

**Undetectable truncation (disclosed).** A reader cannot detect deletion of the
final segment, or removal of whole trailing lines at a line boundary from the
final segment. The remaining chain is self-consistent. The only completeness
anchor is the terminal `ChainHead` that WORKER returns to the controller, and
`attempt_status` is never proof of completeness. The documentation and readiness
records must say so.

## 8. Projection, liveness, pages and reader view (`run_status_projection.py`)

The module performs no direct filesystem primitive; all reads go through
section 10's `run_status` API.

**Projection.**

- `project_assignment` replays only from the index and journals, and caches
  nothing.
- It returns a public `projection` that passes the structural checker. The
  projection contains only verified attempts, in index order, each with its last
  `journal_seq`, `segment_index` and `segment_sha256`.
- Unknown attempts are listed separately with their diagnostics.
- The latest attempt is the last index entry. If that attempt is unknown, the
  latest is unknown; there is no fallback to an earlier attempt.
- `projection.state` is the replayed journal state, not a liveness claim.
- `check_projection(projection, root)` compares a supplied (possibly cached)
  projection with a fresh replay. It returns `projection_behind_journal`
  (display `stale`), `projection_not_from_journal` (refused) or nothing (display
  `current`).

**Liveness.**

- `attempt_status(root, attempt_id, *, observer)` is the only per-attempt display
  surface.
- For a non-terminal attempt it calls `observer(owner_pid)`, which returns
  `(live, start_identity)`.
- If the owner is not live, or the start identity differs from the recorded
  `process_start_time` (pid reuse), the result is `owner_not_live` with display
  `stale_unknown`, never `running`.
- `proc_observer(pid)` is `(identity is not None, identity)`, where `identity` is
  `process_start_identity(pid)`.
- Tests may pass an observer that returns vector observations. The comparison
  itself stays in production code.

**Pages.**

- `read_page(root, request_bytes, *, evidence)` checks the request against
  `page_request`. A null `page_size` or one above 100 refuses `read_unbounded`. A
  size below 1 refuses `page_size_invalid` (local). The page key is
  `request.assignment_digest`.
- Events are verified non-header lines, in index order and then seq order,
  spanning at most 20 attempts (`attempts_per_page_max`).
- Header lines are never page events. They count in `omitted.before` and
  `omitted.after`, as V-page shows.
- `has_more` and `omitted` are always set. `omitted.retention_dropped` counts the
  refs in the window that `evidence(identity, ref)` reports as
  `retention_dropped`.
- The `evidence` resolver is required. It has type
  `Callable[[AttemptIdentity, Ref], str]` and returns `present`,
  `retention_dropped` or `unknown`. Journal ref locators may be null, so WORKER
  maps the attempt identity and ref to its own evidence directory. A result of
  `unknown` adds the local diagnostic `evidence_unknown`.
- Unknown attempts contribute no lines and are listed in the result's
  diagnostics.
- `PageResult(page, next_cursor, diagnostics)`: `next_cursor` is the
  continuation cursor when `has_more` is true, and `None` otherwise. The public
  `page` has no cursor member.

**Cursor.**

- A cursor is `rs1.` + base64url of the JCS bytes of `{assignment_digest,
  index_seq, seq, index_prefix_sha256}`.
- A cursor refuses `cursor_invalid` (local) when its assignment differs, its
  position is out of range, or its index prefix no longer matches.
- Cursors carry no authority.

**Checkers and reader view.**

- `check_page(request, page)` and `check_reader_view(view)` apply the public
  semantic rules to supplied records. Every page and view the production code
  builds must pass the structural checker and its semantic checker before it is
  returned.
- `build_reader_view(row, status, *, work_outcome=None, evidence=None)` composes
  the public `reader_view`.
  - `display.runtime_state` comes only from the closed phrase set in section 9.
  - `work_outcome.source` must be `work_result_reducer`, and `evidence.source`
    must be `requirement_admission`. A `run_status` source refuses
    `runtime_not_work_outcome`.
  - A row whose assignment or snapshot differs from the run record refuses
    `run_record_foreign`.
  - `completed` termination is runtime data only.

## 9. Closed phrase sets (writer and display only)

**Event phrases (owner ruling).** These are the only text `AttemptWriter.event`
writes. Additions need a plan amendment.

- `attempt queued`
- `worker process started`
- `proposal bytes captured`
- `output streams digested`
- `attempt evidence bound`
- `cancellation requested`
- `workspace audit failed; proposal withheld` (audit failures only)
- `evidence retention state recorded`
- `proposal withheld` (every other withholding: incomplete, oversized,
  malformed and the like)

**`runtime_state` phrases (display).** `queued`, `running`, `cancelling`,
`finished (completed)`, `finished (cancelled)`, `finished (timed_out)`,
`finished (failed_to_start)`, `refused`, `unknown` and `stale_unknown`.

## 10. Python surface frozen by IF-0-JOURNAL-1

```text
# run_status.py (SL-0)
JOURNAL_FAMILY = "supervised_run_status.v1"; INDEX_SCHEMA = "phase_loop.supervised_admission_index.v1"
AttemptIdentity(assignment_digest, envelope_digest, run_id, attempt_id)        # frozen dataclasses
Units(target_unit_ids, readonly_neighbor_unit_ids, snapshot_ref)
WriterIdentity(harness_id, harness_version, writer_instance_id, owner_pid, process_start_time)
Ref(kind, sha256, locator); Termination(reason, signal, by); TerminalRefusal(reason, constraint, tier)
ResultBinding(envelope_digest, run_id, attempt_id, proposal_bytes_digest, evidence_envelope_digest)
Reservation(identity, units, index_seq, entry_sha256, writer)   # writer minted by reserve_attempt
ChainHead(segment_index, segment_sha256, last_seq)
JournalLimits(...section 6...); DEFAULT_LIMITS; JournalRoot; JournalRefused(code)
AttemptRead(attempt_id, identity, units, writer, lines, state, terminal, chain_head, diagnostics, display)
IndexRead(assignment_digest, entries, head_sha256, diagnostics)
default_journal_root() -> Path
open_journal_root(path: Path, *, create: bool, excluded: tuple[Path, ...] = ()) -> JournalRoot | JournalRefused
process_start_identity(pid: int) -> str | None
make_ref(kind: str, data: bytes, locator: str | None) -> Ref
reserve_attempt(root, identity, *, units, launch_digest, caller_context_sha256) -> Reservation | JournalRefused
open_writer(root, reservation, *, limits=DEFAULT_LIMITS) -> AttemptWriter | JournalRefused
AttemptWriter.state(state, *, worker_invocations) -> ChainHead | JournalRefused
AttemptWriter.event(phrase, *, refs=()) -> ChainHead | JournalRefused
AttemptWriter.terminal(state, *, worker_invocations, termination, refusal, result_binding) -> ChainHead | JournalRefused
AttemptWriter.close() -> None
read_attempt(root, attempt_id) -> AttemptRead
read_index(root, assignment_digest) -> IndexRead
resolve_run(root, run_id) -> tuple[str, ...] | JournalRefused        # () when the run is absent

# run_status_projection.py (SL-1)
ProcessObserver = Callable[[int], tuple[bool, str | None]]
EvidenceResolver = Callable[[AttemptIdentity, Ref], str]
ProjectionResult(projection, unknown_attempts, diagnostics)
AttemptStatus(attempt_id, state, display, termination, refusal, result_binding, chain_head, diagnostics)
PageResult(page, next_cursor: str | None, diagnostics)
project_assignment(root, assignment_digest) -> ProjectionResult
check_projection(projection: Mapping, root) -> tuple[str, ...]
attempt_status(root, attempt_id, *, observer: ProcessObserver = proc_observer) -> AttemptStatus
read_page(root, request: bytes, *, evidence: EvidenceResolver) -> PageResult | JournalRefused
check_page(request: Mapping, page: Mapping) -> tuple[str, ...]
build_reader_view(row: Mapping, status: AttemptStatus, *, work_outcome=None, evidence=None) -> Mapping | JournalRefused
check_reader_view(view: Mapping) -> tuple[str, ...]
proc_observer(pid: int) -> tuple[bool, str | None]
```

Names and signatures do not change during execution without a plan amendment.
Records are immutable. Exceptions from I/O or parsing are translated to closed
codes `from None`. Diagnostics and refusals carry codes only, never input values,
paths or exception text. `termination`, `refusal` and `result_binding` pass
through `AttemptStatus` unchanged.

## 11. Consumer obligations and downstream amendments

These are named by the 2026-11-08 board on agent-harness#1925 and
agent-harness#1926. They are not made by this phase; each owning plan amends
itself.

- **WORKER**
  - After `consume_admission`, call `reserve_attempt` before any chain spawn,
    and treat any `JournalRefused` as a zero-invocation refusal.
  - Keep reservation and writer in the launcher process that owns the leader.
  - Take the cancel nonce and start identity from `Reservation.writer` at launch
    (J3). For a later cancel, read them from `read_attempt(root, attempt_id).writer`.
  - Take the page key from `read_attempt(...).identity.assignment_digest`.
  - Map `status --run|--attempt` to `resolve_run` / `attempt_status` (J4).
  - Supply an `EvidenceResolver(identity, ref)` backed by `output_retention` (J5).
  - Use `default_journal_root()`, which equals `<state_root>/journal` (J6).
  - Pass workspace, target and reference roots as `excluded`.
  - Emit only section 9 phrases, using `proposal withheld` for every withholding
    except audit failures. Build refs with `make_ref`.
  - Put `ChainHead.last_seq` and `segment_sha256` from the terminal append into
    `--result`.
  - Never signal a pid or pgid read from a journal.
- **LANEEXEC**
  - Map the `unknown`, `stale_unknown`, `refused` and finished displays.
  - Reject run and attempt ids over 128 characters before the claim.
  - Map `attempt_reserved` and specify the crash states between its exec claim
    and WORKER's reservation.
  - Reconcile its per-client roots, selected through trusted configuration, with
    the fixed-root ruling in section 2.
  - Drop `-n 0`.
- **PLACECLI**
  - Narrow `OpaqueId` to 128 characters wherever ids flow into the journal, and
    never truncate.
  - State that its reservation journal is a separate store.
  - Drop `-n 0`.
- **CLOSEOUT**
  - Rerun the vector harness and production entries under the v2 intake (same
    run-status bytes), and reconcile any local code that public v2 renames.
  - Bind the six v2 `kind=echo` cases to WORKER's `caller_context` JCS digest in
    `reserve_attempt`'s index entry, compared by exact bytes, not through the
    journal writer. Mutate `__proto__` loss and a number change before hashing.
  - Add `test_run_status_receipt.py` to the V2 group.
  - Keep the contract-intake allowlist unchanged; `run_status*` stays off it.
  - Apply the `-n` rule.

## 12. Vector ownership (all 35 `run-status.vectors.json` cases)

| Kind (count) | Production entry | Lane |
| --- | --- | --- |
| journal (19) | materialize to disk, then `read_index` + `read_attempt` | SL-0 |
| projection (4) | `project_assignment` / `check_projection` | SL-1 |
| liveness (3) | `attempt_status` with a vector-observation observer | SL-1 |
| reader_view (5) | `check_reader_view` and `build_reader_view` | SL-1 |
| page (4) | `check_page`; V-page also re-derived through `read_page` | SL-1 |

`tests/_run_status_vectors.py` (SL-0) is test-only and may import the intake
module. It:

- loads the corpus through `load_contract_bundle().resource_bytes`;
- applies the RFC 6902 add/remove/replace patches with RFC 6901 pointers, and
  asserts each edit took effect;
- materializes `journal` inputs to a temporary root: an index entry per attempt
  in listed order, and segments as listed (an object line as JCS, a string line
  raw, a final LF unless `final_newline: false`), with modes 0700/0600 under
  umask 077;
- exposes `validate_record` for the differential cross-check.

It has no semantic logic, and its output only enters production readers and
checkers.

## 13. Named mutation controls

Use the ENVELOPE pattern (`tests/test_supervised_launch_mutations.py`). Each
control replaces exactly one asserted-present source fragment, execs the mutated
module under a temporary name, and makes a witness that passes on production
fail. Controls live in the owning lane's test file.

- **SL-0:** `index_lock`, `index_fsync`, `assignment_dir_fsync`,
  `run_claim_fsync`, `attempt_excl`, `run_claim`, `index_chain`,
  `index_torn_refusal`, `component_nofollow`, `owner_check`, `mode_check`,
  `nlink_check`, `torn_line`, `unknown_version`, `foreign_writer`,
  `writer_instance_reuse` (`open_writer` mints instead of copying), `seq_gap`,
  `segment_chain`, `missing_segment`, `identity_key`, `lifecycle_order`,
  `refused_after_launch`, `phrase_set`, `writer_poison`, `ref_digest_only`,
  `locator_rule`, `line_cap`, `terminal_headroom`, `reader_readonly`,
  `structural_check`.
- **SL-1:** `index_order` (replace with lexical or mtime order),
  `latest_fallback`, `projection_behind`, `projection_ahead`, `owner_live`,
  `pid_reuse`, `page_bound`, `page_attempt_bound`, `header_not_event`,
  `omitted_counts`, `retention_count`, `next_cursor`, `cursor_binding`,
  `outcome_source`, `row_join`, `runtime_phrase_set`.
