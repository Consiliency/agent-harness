# Supervised run status: attempt journal and projection

JOURNAL implements the local seam IF-0-JOURNAL-1 for agent-harness#1818. It gives the
supervised worker one authoritative, append-only history per attempt, a durable
per-assignment admission index, and replaceable replay views over them. The
acceptance criteria are EC-JOURNAL-1 through EC-JOURNAL-4 in
[`specs/phase-plans-v12.md`](../specs/phase-plans-v12.md). The frozen interface is
[`plans/artifacts/v12-JOURNAL-interface.md`](../plans/artifacts/v12-JOURNAL-interface.md).
Observed offline evidence is in
[the JOURNAL receipt](../plans/evidence/supervised-worker/JOURNAL.md).

This is an internal Python API. It adds no CLI, provider integration, live-use
authority or public contract conformance. CLOSEOUT still owns authoritative
acceptance against the pinned publication.

**Run status is never a work outcome.** It records runtime state and digests of
native results. A `finished (completed)` attempt says only that the worker process
ended normally. It says nothing about whether the work is correct or admitted.

## Contract inputs

Journal lines are exactly the public `supervised_run_status.v1` `journal_line`
records from the vendored
`phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/run-status.schema.json`.
Its bytes are identical at the v1 and v2 consiliency-contract pins. The publisher
status is `provisional`.

The runtime validates structure with the standard library plus `rfc8785`. A closed
checker (`run_status.check_structure`, with tables in `run_status.STRUCTURE`)
mirrors the five public definitions: `journal_line`, `projection`,
`page_request`, `page` and `reader_view`. Tests check its tables against the pinned
schema and compare its verdict with the pinned validator on every vector and
produced record. Runtime modules never import the contract-intake module.

## API

`phase_loop_runtime.run_status` (SL-0):

| Name | Purpose |
| --- | --- |
| `default_journal_root()` | the fixed per-user root (below) |
| `open_journal_root(path, *, create, excluded=())` | verify (and optionally create) a root; returns `JournalRoot` or `JournalRefused` |
| `reserve_attempt(root, identity, *, units, launch_digest, caller_context_sha256)` | durable, atomic claim of an attempt id; returns `Reservation` |
| `open_writer(root, reservation, *, limits=DEFAULT_LIMITS)` | the single, never-resumed `AttemptWriter` |
| `AttemptWriter.state` / `.event` / `.terminal` / `.close` | appends returning `ChainHead(segment_index, segment_sha256, last_seq)` |
| `read_attempt(root, attempt_id)` | one bounded, read-only replay of one attempt (`AttemptRead`) |
| `read_index(root, assignment_digest)` | the verified admission index (`IndexRead` of `IndexEntry`) |
| `read_attempt_window(root, index, entry, *, after_seq=-1, max_events=0, earlier_evidence=frozenset(), event_kinds=EVENT_KINDS, prefix_at=None)` | the same verification as `read_attempt`, retaining at most `max_events` (≤ 100) lines and only the requested segment's summary (`AttemptWindow`) |
| `resolve_run(root, run_id)` | the attempt ids of a run, in index order; `()` for an absent run |
| `process_start_identity(pid)` | `linux-proc:<boot_id>:<starttime>` for a live process, else `None` |
| `make_ref(kind, data, locator)` | a digest-only `Ref`; `data` is hashed and dropped |

`phase_loop_runtime.run_status_projection` (SL-1):

| Name | Purpose |
| --- | --- |
| `project_assignment(root, assignment_digest)` | `ProjectionResult(projection, unknown_attempts, diagnostics)` |
| `check_projection(projection, root)` | compare a supplied projection with a fresh replay |
| `attempt_status(root, attempt_id, *, observer=proc_observer)` | the only per-attempt display surface (`AttemptStatus`) |
| `read_page(root, request_bytes, *, evidence)` | `PageResult(page, next_cursor, diagnostics)` |
| `check_page(request, page)` / `check_reader_view(view)` | public semantic rules for supplied records |
| `build_reader_view(row, status, *, work_outcome=None, evidence=None)` | the public `reader_view` |
| `proc_observer(pid)` | `(identity is not None, identity)` from `process_start_identity` |

`EvidenceResolver` is `Callable[[AttemptIdentity, Ref], str]` and returns
`present`, `retention_dropped` or `unknown`. `ProcessObserver` is
`Callable[[int], tuple[bool, str | None]]`.

All records are frozen dataclasses. Diagnostics and refusals carry closed codes
only, never input values, paths or exception text. Beyond the frozen artifact the
implementation adds these names: `IndexEntry`, `TerminalRecord`, `check_structure`,
`STRUCTURE`, `AttemptWindow`/`read_attempt_window`, and two trailing defaulted
fields on `AttemptStatus` (`identity`, `units`) that `build_reader_view` needs to
fill the public `run_record`. Revision 3 of the frozen interface lists them all.

## Root and storage layout

`default_journal_root()` takes no arguments. It returns
`<pw_dir>/.local/state/agent-harness/supervised-worker/journal`, where `pw_dir` comes
from the password database entry for the effective uid. It never reads `HOME`,
`XDG_STATE_HOME` or any other environment variable, so every tool finds one fixed
per-user journal. `open_journal_root` also accepts an explicit absolute root, but only
from in-process tests or trusted operator configuration.

```text
<root>/                                  0700, owner = euid
  attempts/<attempt_id>/                 0700, created exclusively by reserve_attempt
    lock                                 0600, held LOCK_EX by the single writer
    0000.jsonl, 0001.jsonl, ...          0600 segments, contiguous from 0000
  assignments/<assignment_digest>/       0700
    lock                                 0600, per-assignment reservation lock
    index.jsonl                          0600, append-only admission index
  runs/<run_id>                          0600, exactly "<assignment_digest>\n"
```

The journal must sit outside the target repository. It is also outside every
`output_retention` root. Nothing prunes it.

## Trust checks

- `open_journal_root` refuses `journal_root_unsafe` for a relative path, a `..`
  component, any symlink component, a root that equals, sits inside or contains an
  `excluded` root (compared lexically, through `realpath`, and by device and inode
  along the opened chain), or a root whose owner or mode is wrong.
- With `create=True`, each missing component is made with `mkdir` 0700 and an
  explicit `fchmod`. The parent of every component this account owns is fsynced,
  whether the component was created now or adopted, and the root is fsynced once
  its subdirectories exist. An existing directory with the wrong mode is refused,
  never repaired. `create=False` on an absent root refuses `journal_missing` and
  fsyncs nothing.
- Every later open walks from `/` one component at a time with `O_NOFOLLOW` and
  `dir_fd`. The root must still have the device and inode that `open_journal_root`
  recorded.
- `fstat` must show the effective uid as owner. Directories need exact mode 0700.
  Files need exact mode 0600, a regular file and `st_nlink == 1`. Readers report a
  violation as `journal_path_unsafe` (display `unknown`). Writers and reservations
  refuse with it.
- Readers open read-only, with `O_NONBLOCK` so a planted FIFO cannot block them.
  They never create, truncate, rename, unlink, chmod or break a lock.

## Identifiers

`run_id` and `attempt_id` must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. The
128-character ceiling is the public `maxLength`. Longer ids are refused, never
truncated. Digests (`assignment_digest`, `envelope_digest`, `snapshot_ref`,
`launch_digest`, `caller_context_sha256`) must be lowercase 64-hex. Unit ids are
1–200 characters. A violation refuses `identifier_invalid` before any filesystem
effect.

`caller_context` enters only as `caller_context_sha256`, which the caller computes
over the RFC 8785 bytes of the admitted value. JOURNAL never receives the value.

## Reservation and fsync order

`reserve_attempt` mints the writer identity once: harness id `phase-loop-runtime`,
the package version, a 128-bit random lowercase-hex `writer_instance_id`, the current
pid and its process start identity.

**Barrier rule.** Every fsync below runs on every reservation. It runs whether
this call created the entry or adopted one left by a creator that was killed, or
whose fsync failed, before reaching it. A reservation therefore never acknowledges
an entry whose durability chain is incomplete. An fsync failure refuses
`journal_write_failed`. The steps are:

1. Create `assignments/<digest>` if it is absent, then fsync `assignments/`.
2. Open or create `lock`, then fsync the assignment directory. Take `LOCK_EX`.
   Steps 3 to 7 run under this lock.
3. Read and verify the whole index: canonical JCS lines, the hash chain, gapless
   `index_seq`, schema and version, the directory key, unique attempt ids, no
   torn tail and the size caps. Any defect refuses `index_unverifiable`. The index
   is never repaired.
4. An attempt id already in the index refuses `attempt_reserved`.
5. Run claim. An existing `runs/<run_id>` must hold exactly this assignment's
   digest, and is then adopted. Another digest refuses `run_assignment_mismatch`.
   An empty, short, malformed or unsafe record refuses `run_record_unreadable`.
   An absent record is created exclusively and written fully. Created or
   adopted, the claim file and then `runs/` are fsynced.
6. `mkdir attempts/<attempt_id>` (exclusive) and fsync `attempts/`. If it already
   exists, refuse `attempt_reserved`. This also covers ids used by another
   assignment and ids left by a crashed reservation.
7. Append the entry with `O_APPEND` and a full-write loop, then fsync the index
   and the assignment directory.

Every reservation fsyncs, in order, `assignments/`, the assignment directory,
`runs/<run_id>`, `runs/`, `attempts/`, `index.jsonl`, then the assignment directory
again. The result is `Reservation(identity, units, index_seq, entry_sha256,
writer)`.

### Crash windows

| Crash after | Effect |
| --- | --- |
| step 1 or 2 | an empty assignment; harmless |
| inside step 5 | an empty or short run record; that run id refuses `run_record_unreadable` until quarantine |
| step 5 | a valid run claim with no attempt; harmless, and `resolve_run` returns `()` |
| step 6 | the attempt id can never be reused; readers report `journal_missing` and `attempt_unindexed` |
| a torn index append | the assignment is `index_unverifiable` for readers and reservations |
| before any barrier, or a failed fsync | the next reservation adopts the entries and completes every barrier before it acknowledges |

### Manual quarantine

v12 has no automatic recovery, and quarantine never releases a claim.

- **Torn index.** Stop the affected worker. Rename the assignment directory aside
  within `assignments/`, under a name that is not 64-hex, for example
  `assignments/<digest>.quarantined-<date>`, and keep its bytes. New reservations
  for that assignment start a fresh index. Every attempt id the old index held
  stays claimed through `attempts/`, and every run id through `runs/`. The old
  attempts then read `attempt_unindexed`.
- **Run records.** Never rename, move or delete one. An empty, short, malformed or
  unsafe record stays at its key as a permanent tombstone, and that run id refuses
  `run_record_unreadable` from then on. Use a new run id. To keep forensic bytes,
  copy the record elsewhere and leave the original in place.

Nothing deletes or rewrites journal files. A sealed recovery record is deferred
to a later phase.

## Writer

`open_writer` checks three things. The calling process must have the reservation's
`owner_pid` and process start identity, otherwise it refuses
`writer_identity_mismatch`. The reservation must match its index entry, otherwise
it refuses `attempt_unindexed`. The limits must be valid, otherwise it refuses
`limits_invalid`.

It then creates the attempt `lock` exclusively, or adopts an existing one, and
fsyncs the attempt directory either way. It takes `LOCK_EX | LOCK_NB`; a busy lock
refuses `journal_writer_busy`. Any existing segment refuses
`journal_exists`, so a writer is never resumed. It creates `0000.jsonl` with its
header and fsyncs the file and the attempt directory. It copies `Reservation.writer`
unchanged into every line and never mints a second id.

- Each line is RFC 8785 bytes plus LF, written fully and then fsynced. A rotation
  creates the next segment exclusively with a header naming the previous segment's
  SHA-256 and last seq, then fsyncs the file and the directory.
- **Lifecycle.** This is `x-journal-rules.lifecycle`, enforced before any byte is
  written. The first state must be `queued`. `finished` requires a termination.
  `refused` requires a refusal, zero invocations, no earlier `running` and no result
  binding. `worker_invocations` never decreases. Nothing follows a terminal line. A
  result binding must name the attempt's own envelope, run and attempt ids
  (`attempt_provenance_mismatch`). Violations refuse `lifecycle_invalid` and write
  nothing.
- **Events.** Event text must be one of the closed phrases below, otherwise the
  event refuses `phrase_invalid`. Refs must be `Ref` records from `make_ref`, at
  most 16 per event, otherwise `ref_invalid`. Locators are null or
  repository-relative: non-empty, not absolute, no `..` segment and no backslash.
- **Line cap.** `per_attempt_line_cap` counts every line of the attempt, headers
  included. A non-terminal append, with any rotation header it causes, may not bring
  the total above cap − 2. The terminal line always fits. A refused append returns
  `event_cap_reached`.
- **Poisoning.** Any `OSError`, short write or fsync failure during an append or
  rotation returns `journal_write_failed` and poisons the writer. Every later
  `state`, `event` or `terminal` refuses `writer_poisoned` and writes nothing. A
  partial line stays on disk, where readers report `journal_torn_line`. `close()`
  releases the lock and descriptors; later appends refuse `writer_closed`.

| Limit | Default | Source |
| --- | --- | --- |
| `per_attempt_line_cap` | 10000 lines, headers included, last 2 reserved | public `per_attempt_event_cap` (provisional reading) |
| `event_message_max_chars` | 200 | public |
| `segment_max_lines` / `segment_max_bytes` | 1000 / 1 MiB | local |
| `read_segment_max_bytes` | 4 MiB | local |
| `index_max_entries` | 100000 (index read cap 64 MiB) | local |

`open_writer` refuses `limits_invalid` for any limit above these reader bounds:
`per_attempt_line_cap` at most 10000, `segment_max_bytes` and
`read_segment_max_bytes` at most 4 MiB, and `index_max_entries` at most 100000.
Readers always replay with the defaults, so every journal an admitted writer
finishes reads back cleanly.
| page size / attempts per page | 100 / 20 | public |

## Reader rules and diagnostics

Readers make one bounded pass. Segments are ordered by parsed integer index, never
by mtime, wall clock or directory order. Readers apply only the structural checker,
the public `x-semantic-rules` and the local codes below. They never enforce the
writer-only rules (harness id, hex instance id, `linux-proc:` encoding, closed
event phrases), so any schema-valid writer strings and public-rule-conforming
messages read clean. Any diagnostic makes an attempt display `unknown`.

Public codes are used unchanged: `journal_torn_line`, `journal_malformed_line`,
`journal_unknown_version`, `journal_foreign_writer`, `attempt_overwritten`,
`attempt_provenance_mismatch`, `attempt_evidence_copied`, `refused_after_launch`,
`lifecycle_invalid`, `raw_output_in_record`, `locator_not_repo_relative`,
`projection_behind_journal`, `projection_not_from_journal`, `owner_not_live`,
`run_record_foreign`, `runtime_not_work_outcome` and `read_unbounded`.

After an unparseable or structurally invalid line, the reader stops checking seq
continuity and lifecycle for the rest of that attempt. The attempt is already
unknown.

Local codes never appear in a public record:

| Code | Meaning |
| --- | --- |
| `journal_missing` | attempt directory or segment `0000` absent, or root absent with `create=False` |
| `journal_unexpected_entry` | an entry other than `lock` and `NNNN.jsonl` |
| `journal_path_unsafe` | owner, mode, link, type, nlink or root binding check failed |
| `journal_oversize` | a segment, line count or directory scan over a read cap |
| `attempt_unindexed` | an attempt directory with no index entry |
| `index_unverifiable` | index chain, sequence, schema, key, canonical form, torn tail or size defect |
| `run_record_unreadable` | run record empty, short, malformed or unsafe (refusal) |
| `journal_root_unsafe`, `identifier_invalid`, `liveness_unsupported`, `attempt_reserved`, `run_assignment_mismatch` | reservation and root refusals |
| `writer_identity_mismatch`, `journal_writer_busy`, `journal_exists`, `limits_invalid`, `journal_write_failed`, `writer_poisoned`, `writer_closed`, `event_cap_reached`, `phrase_invalid`, `ref_invalid` | writer refusals (`journal_write_failed` also covers a failed reservation or root barrier) |
| `page_size_invalid`, `page_request_invalid`, `page_invalid`, `cursor_invalid`, `evidence_unknown` | page refusals and diagnostics |
| `reader_view_invalid`, `runtime_state_invalid`, `run_record_unknown` | reader-view refusals and checks |

`attempt_provenance_mismatch` covers four mismatches: a line's identity against the
first line; that line's attempt id against the directory name; the header's
identity and units against the index entry; and a terminal result binding against
its line. An index-entry writer that differs from the header writer is
`journal_foreign_writer`. `attempt_evidence_copied` compares a terminal's
evidence-envelope digest with earlier attempts of the same assignment, in index
order.

### Undetectable truncation

A reader cannot detect deletion of the final segment, or removal of whole trailing
lines at a line boundary from the final segment, because the remaining chain is
self-consistent. The only completeness anchor is the terminal `ChainHead` that
WORKER returns to its controller. `attempt_status` is never proof of completeness.

## Projection, liveness, pages and reader views

`run_status_projection` replays on every call and caches nothing. It performs no
filesystem primitive of its own; every read goes through `run_status`.

- **Projection.** Only verified attempts appear, in admission-index order, each with
  its last `journal_seq`, `segment_index` and `segment_sha256`. Unknown attempts are
  listed separately with their diagnostics. The latest attempt is the last index
  entry. When it is unknown, `project_assignment` returns no projection, so no
  earlier attempt stands in for it. `check_projection` returns nothing for a current
  projection, `projection_behind_journal` (display stale) for a behind or
  incomplete projection, and `projection_not_from_journal` (refused) for one that is
  ahead, forged, reordered or not derivable from the journal. An index defect also
  gives `projection_not_from_journal`.
- **Liveness.** For a non-terminal attempt, `attempt_status` calls the observer
  with the recorded `owner_pid`. If the owner is not live, or its start identity
  differs from the recorded `process_start_time` by exact string equality (pid
  reuse), the result is `owner_not_live` with display `stale_unknown`, never
  `running`. A failing or malformed observer counts as not live. Terminal attempts
  never consult the observer. `termination`, `refusal` and `result_binding` pass
  through unchanged.
- **Bounded reads.** `read_page`, `project_assignment` and `check_projection` load
  the index once and read each attempt once, in index order, through
  `read_attempt_window`. They retain only the selected events (at most
  `page_size`) and count every other verified line. Each attempt's
  evidence-envelope digest is carried forward to the later attempts' copy check,
  so no earlier attempt is rescanned. Peak memory is bounded by the index, one
  segment (`read_segment_max_bytes`) and the page, not by the assignment's
  history.
- **One replay per projection call.** `project_assignment` and `check_projection`
  each make exactly one index load and one window per attempt. Per attempt they
  keep only the head-derived projection row and, when checking a supplied row,
  one digest verdict computed from the requested segment in-stream. No segment
  list or line outlives its attempt. `project_assignment` validates its result
  against that same replay instead of reading the journal again.
- **Behind rows.** A row behind the tail is stale only when both its digest and
  its `state` derive from the journal. A prefix digest at its `journal_seq` must
  carry the replayed state at that seq. The full current segment digest must
  carry the current state. Anything else, such as a historical digest with an
  edited state, is `projection_not_from_journal`.
- **Pages.** The request must be a structurally valid `page_request`
  (`page_request_invalid`). A null `page_size` or one above 100 refuses
  `read_unbounded`, and one below 1 refuses `page_size_invalid`. Events are
  verified non-header lines in index order, then seq order, from at most 20
  attempts. Header lines are never events. `omitted.before` and `omitted.after`
  count every line, headers included, before the first and after the last returned
  event. `has_more` and `omitted` are always present. `retention_dropped` counts
  the window's refs that the required resolver reports as `retention_dropped`. An
  `unknown` result, or a failing resolver, adds `evidence_unknown`. Unknown attempts
  contribute no lines, and their codes appear in the result's diagnostics.
- **Cursor.** `next_cursor` is present exactly when `has_more` is true. It is
  `rs1.` plus unpadded base64url of the JCS bytes of `{assignment_digest,
  index_seq, seq, index_prefix_sha256}`, where the prefix digest is the index
  entry's chained SHA-256. A cursor refuses `cursor_invalid` when it is
  non-canonical, foreign to the request's assignment, out of range or bound to an
  index prefix that no longer matches. Cursors carry no authority; continuation
  works after further appends.
- **Reader view.** `display.runtime_state` comes only from the closed phrases below.
  `work_outcome.source` must be `work_result_reducer`, and `evidence.source` must be
  `requirement_admission`; a `run_status` source refuses `runtime_not_work_outcome`.
  A row whose assignment digest or snapshot differs from the run record refuses
  `run_record_foreign`. An unknown attempt has no run record and refuses
  `run_record_unknown`.

Every projection, page and view that production builds passes the structural
checker and its semantic checker before it is returned.

## Closed phrase sets

Event phrases, the only text `AttemptWriter.event` writes:

- `attempt queued`
- `worker process started`
- `proposal bytes captured`
- `output streams digested`
- `attempt evidence bound`
- `cancellation requested`
- `workspace audit failed; proposal withheld` (audit failures only)
- `evidence retention state recorded`
- `proposal withheld` (every other withholding)

`runtime_state` phrases: `queued`, `running`, `cancelling`, `finished (completed)`,
`finished (cancelled)`, `finished (timed_out)`, `finished (failed_to_start)`,
`refused`, `unknown` and `stale_unknown`.

## Platform and trust boundary

The supervised worker and the journal writer are **Linux-only** in v12, because
process start identity comes from `/proc/sys/kernel/random/boot_id` and
`/proc/<pid>/stat` field 22. Elsewhere, reservation and `open_writer` refuse
`liveness_unsupported`. Readers still work.

**Unsupported trust boundary.** Writer binding is not authentication. Any process
running as the same login can forge a self-consistent chain, index or run record,
and can read every journal. The per-user root, ownership and mode checks keep other
accounts out. They do not protect against the same account.
