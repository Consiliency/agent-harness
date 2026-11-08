# JOURNAL frozen interface (IF-0-JOURNAL-1)

Planning artifact for `plans/phase-plan-v12-JOURNAL.md` (agent-harness#1818).
This is a harness-local seam contract, not a public wire schema. The plan's
manifest entry seals this file by SHA-256 under `frozen_inputs`; a change needs a
reviewed plan amendment and a reseal. Roadmap EC IDs remain the only acceptance
authority. This file restates no EC text.

## 1. Inputs and their status

Recorded 2026-11-08 by hashing the vendored files and fetching the same paths
from public Consiliency/consiliency-contract at both pinned commits:

| Resource (vendored under `schemas/supervised-worker-v1/`) | SHA-256 | v1 pin `93db4b4f…` | v2 pin `2b91ef85…` |
| --- | --- | --- | --- |
| `run-status.schema.json` | `5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30` | identical | identical |
| `conformance/run-status.vectors.json` | `5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730` | identical | identical |

The run-status family therefore has one byte-identical public definition across
the SCHEMA intake, the CLOSEOUT intake and the v13 `x-contract-pins.run_status`
pin. JOURNAL uses these vendored bytes as its vocabulary and record validator
through the landed `supervised_contracts.load_contract_bundle()` and
`validate_record(bundle, "supervised_run_status.v1", raw, definition=…)`. It does
not author names, enums or bounds where the schema already defines them. The
publisher status stays `provisional`. Per the roadmap Execution Notes, CLOSEOUT
still discharges authoritative acceptance under the v2 intake. JOURNAL's vector
runs are early runtime reconciliation evidence, not that discharge.

Harness-local additions (sections 3, 5 and 7) are labelled local. They never
enter a public record, and the admission index uses its own schema name.

## 2. Storage layout and trust checks

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
    <run_id>                             0600, created O_EXCL; holds the run's assignment_digest
```

- `default_journal_root(environ)` is `$XDG_STATE_HOME/phase-loop/supervised-run-status`
  when `XDG_STATE_HOME` is absolute, else `~/.local/state/phase-loop/supervised-run-status`.
  Callers holding trusted operator configuration (WORKER, LANEEXEC per-client inventories)
  may pass any other absolute root.
- `open_journal_root(path, *, create, excluded)` refuses `journal_root_unsafe` for: a
  relative path; any symlink component; a root equal to, inside, or containing an
  `excluded` root (WORKER passes workspace, target and envelope-referenced roots); and a
  wrong owner or mode. With `create=True`, missing components below an existing verified
  parent are created 0700 with an explicit `fchmod`, so umask has no effect.
- Every subsequent open is `dir_fd`-relative with `O_NOFOLLOW` at each component. `fstat`
  must show `st_uid == geteuid()`. Directories need exact mode 0700. Files need exact mode
  0600, `S_ISREG` and `st_nlink == 1`. A violation is `journal_path_unsafe`. Readers report
  it as a diagnostic (display `unknown`). Writers and reservations refuse.
- Readers open `O_RDONLY`. They never create, truncate, rename, unlink, chmod or lock-break.
  Only `reserve_attempt` and `AttemptWriter` write, and only by appending or exclusive creation.
- No listener, watch, inotify or polling loop exists. Every read is one bounded pass.
- Same-login processes can forge a self-consistent chain or index. Writer binding is not
  authentication against them, and readiness documentation must say so.

## 3. Identifier grammar (local)

`run_id` and `attempt_id` must match `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`. They must
not be `.` or `..`, and must be valid single path components. The 128-character ceiling
is the public run-status `maxLength`. The character class equals the v13 PLACECLI
`OpaqueId` class, but the OpaqueId ceiling is 256 (see the plan's consumer-mismatch note).
`assignment_digest`, `envelope_digest`, `snapshot_ref`, `launch_digest` and
`caller_context_sha256` must be lowercase 64-hex. A violation refuses `identifier_invalid`
before any filesystem effect.

## 4. Journal line format

- Lines are the public `journal_line` definition, exactly: `schema`
  (`supervised_run_status.v1`), `version` (`"1"`), `line_kind`, `seq`, `attempt`, `units`,
  `writer`, `observed_at`, `redaction_posture` (`digests_and_repo_relative_locators_only`)
  and `body`.
- Each object line is RFC 8785 (JCS) bytes from the existing `rfc8785` dependency, followed
  by one LF. Segment SHA-256 follows the schema's `x-canonicalization` over the on-disk bytes.
  No dependency or lock change is needed.
- `seq` starts at 0 for the segment-0 header and is gapless across segments. Each segment
  begins with a `header` line. Segment 0 carries `previous_segment_sha256: null` and
  `previous_last_seq: null`. Segment *n* carries the SHA-256 of segment *n-1* and its last seq.
- `writer` = {`harness_id`: `"phase-loop-runtime"`, `harness_version`:
  `phase_loop_runtime.__version__`, `writer_instance_id`: 128-bit random hex per writer,
  `owner_pid`, `process_start_time`}. `process_start_time` is
  `process_start_identity(pid)` = `linux-proc:<boot_id>:<starttime clock ticks>` from
  `/proc/sys/kernel/random/boot_id` and `/proc/<pid>/stat` field 22. Wall-clock conversion
  is not used. If the platform cannot produce it, the writer refuses `liveness_unsupported`.
- `observed_at` is an informational UTC timestamp and never orders anything.
- Every string is at most 512 characters. Event `message` is
  `{label: "untrusted_display_text", text: <phrase>}`, where `<phrase>` comes only from the
  closed set in section 9. `refs` carry `{kind, sha256, locator}` built only by `make_ref`.
  The locator is null or repository-relative: non-empty, not absolute, no `..` segment,
  no backslash.

## 5. Admission index and reservation (local)

An index entry is one JCS line + LF:

```text
{schema: "phase_loop.supervised_admission_index.v1", version: "1", index_seq,
 previous_entry_sha256 (null for index_seq 0), assignment_digest, envelope_digest,
 run_id, attempt_id, launch_digest, caller_context_sha256, units, writer}
```

`reserve_attempt` performs these steps in order. Steps 2–7 run under `LOCK_EX` on the
assignment `lock`:

1. Validate identifiers and digests (section 3).
2. Open the assignment directory, creating it under a verified root if needed.
3. Read and verify the whole index: chain digests, gapless `index_seq`, schema/version,
   per-entry assignment digest equal to the directory key, no torn tail, size within
   limits. Any defect refuses `index_unverifiable`. The index is never repaired.
4. An `attempt_id` already in the index refuses `attempt_reserved`.
5. Create `runs/<run_id>` with O_EXCL holding the assignment digest, or verify an existing
   one names the same assignment. A different assignment refuses `run_assignment_mismatch`.
6. `mkdir attempts/<attempt_id>` with O_EXCL, then `fsync` the parent. EEXIST refuses
   `attempt_reserved`. This covers ids used by another assignment and ids from a reservation
   that crashed before step 7.
7. Append the entry with a full-write loop, `fsync` the index file, and `fsync` the
   directory if the file was created.
8. Return `Reservation`.

Crash windows: after step 5, a dangling run claim is harmless. After step 6, the attempt
can never be reused, and readers report it `attempt_unindexed` (display `unknown`). A torn
index tail makes the assignment `index_unverifiable` for both readers and reservations.
Recovery is an operator action outside this phase (plan open question 2). `caller_context`
enters only as `caller_context_sha256`: the SHA-256 of the RFC 8785 bytes of the exact
admitted value, computed by the caller. JOURNAL checks only that it is 64-hex and never
receives the value. The reserving process's writer identity is recorded,
and `open_writer` refuses `writer_identity_mismatch` unless the current process has the same
`owner_pid` and `process_start_time`.

## 6. Writer

`open_writer` takes `LOCK_EX | LOCK_NB` on `attempts/<attempt_id>/lock` (busy refuses
`journal_writer_busy`). It refuses `journal_exists` if any segment exists, so a writer is
never resumed. It then creates `0000.jsonl` with O_EXCL and writes the header. Every append
is a full write, then `fsync` of the file, plus the directory when a file was created. Each
returns the new `ChainHead`.

The lifecycle is the schema's `x-journal-rules.lifecycle`, enforced before any byte is
written. The first state line must be `queued`. `finished` requires `termination`.
`refused` requires `refusal`, `worker_invocations == 0` and no earlier `running`.
`worker_invocations` never decreases. Nothing follows a terminal line. A violation refuses
`lifecycle_invalid` and writes nothing.

Rotation happens before an append that would exceed `segment_max_lines` or
`segment_max_bytes`. The new segment is created O_EXCL with its chained header.

Caps (provisional local defaults; public bounds where the schema names them):

| Limit | Default | Source |
| --- | --- | --- |
| `per_attempt_line_cap` | 10000 lines, last slot reserved for the terminal | public `per_attempt_event_cap` |
| `event_message_max_chars` | 200 | public |
| `segment_max_lines` / `segment_max_bytes` | 1000 / 1 MiB | local |
| `read_segment_max_bytes` | 4 MiB | local |
| `index_max_entries` | 100000 | local |

Exceeding the line cap refuses `event_cap_reached` for non-terminal lines.

## 7. Reader rules and diagnostics

`read_attempt` and `read_index` make one bounded pass. Segments are ordered by parsed
integer index, never by mtime, wall clock or directory order. Diagnostic sets are exact
and unordered. For the 19 `kind=journal` vectors the production reader must return exactly
`expected`, and every vector `expected_effect.display` value must match.

Public codes (`x-semantic-rules`) are used unchanged: `journal_torn_line`,
`journal_malformed_line`, `journal_unknown_version`, `journal_foreign_writer`,
`attempt_overwritten`, `attempt_provenance_mismatch`, `attempt_evidence_copied`,
`refused_after_launch`, `lifecycle_invalid`, `raw_output_in_record`,
`locator_not_repo_relative`, `projection_behind_journal`, `projection_not_from_journal`,
`owner_not_live`, `run_record_foreign`, `runtime_not_work_outcome` and `read_unbounded`.

Local codes, which never appear in a public record:

| Code | Meaning | Display |
| --- | --- | --- |
| `journal_missing` | attempt directory or segment 0000 absent | unknown |
| `journal_unexpected_entry` | an entry other than `lock` and `NNNN.jsonl` | unknown |
| `journal_path_unsafe` | owner, mode, link, type or nlink check failed | unknown |
| `journal_oversize` | a segment or line count over a read cap | unknown |
| `attempt_unindexed` | an attempt directory with no index entry | unknown |
| `index_unverifiable` | index chain, sequence, schema, key, torn tail or size defect | unknown |

Identity-versus-key checks produce `attempt_provenance_mismatch`. They compare each line's
`attempt` with the header and with the directory name, the header with its index entry, the
index entry with its assignment directory, and the terminal `result_binding` with the line's
identity. An index-entry writer that differs from the header writer is
`journal_foreign_writer`. `attempt_evidence_copied` compares evidence-envelope digests
across the attempts of one assignment in index order. Any diagnostic sets display `unknown`.
Readers never repair or truncate.

## 8. Projection, liveness, pages and reader view (`run_status_projection.py`)

- `project_assignment` replays only from the index and journals, and caches nothing. It
  returns a schema-valid public `projection` that contains only verified attempts, in index
  order, each with its last `journal_seq`, `segment_index` and `segment_sha256`. Unknown
  attempts are listed separately with their diagnostics. The latest attempt is the last
  index entry. If that attempt is unknown, the latest is unknown, with no fallback to an
  earlier attempt. `projection.state` is the replayed journal state, not a liveness claim.
- `check_projection(projection, root)` compares a supplied (possibly cached) projection with
  a fresh replay. It returns `projection_behind_journal` (display `stale`),
  `projection_not_from_journal` (refused) or nothing (display `current`).
- `attempt_status(root, attempt_id, *, observer)` is the only per-attempt display surface.
  For a non-terminal attempt it calls `observer(owner_pid)`, which returns `(live,
  start_identity)`. If the owner is not live, or its identity differs from the recorded
  `process_start_time` (pid reuse), the result is `owner_not_live` with display
  `stale_unknown`, never `running`. The production observer reads `/proc`. Tests may pass an
  observer that returns vector observations, but the comparison stays in production code.
- `read_page(root, request_bytes, *, evidence)` validates `page_request` through
  `validate_record`. A null `page_size` or one above 100 refuses `read_unbounded`, and a size
  below 1 refuses `page_size_invalid` (local). Events are verified lines in index order then
  seq order, spanning at most 20 attempts (`attempts_per_page_max`). `has_more` and `omitted`
  are always set. `omitted.before` and `omitted.after` count lines outside the window.
  `omitted.retention_dropped` counts window refs that `evidence(ref)` reports as
  `retention_dropped`. `evidence` is a required injected resolver returning `present`,
  `retention_dropped` or `unknown`. WORKER supplies one backed by `output_retention`, and
  `unknown` adds the local diagnostic `evidence_unknown`. Unknown attempts contribute no lines
  and are listed in the result's diagnostics.
- The cursor is `rs1.` + base64url(JCS `{assignment_digest, index_seq, seq,
  index_prefix_sha256}`). A cursor whose assignment differs, whose position is out of range,
  or whose index prefix no longer matches refuses `cursor_invalid` (local). Cursors carry no
  authority.
- `check_page(request, page)` and `check_reader_view(view)` apply the public semantic rules
  to supplied records. Every page and view the production code builds must pass its checker
  before it is returned.
- `build_reader_view(row, status, *, work_outcome=None, evidence=None)` composes the public
  `reader_view`. `display.runtime_state` comes only from the closed phrase set (section 9).
  `work_outcome.source` must be `work_result_reducer` and `evidence.source` must be
  `requirement_admission`. A `run_status` source refuses `runtime_not_work_outcome`. A row
  whose assignment or snapshot differs from the run record refuses `run_record_foreign`.
  `completed` termination is runtime data only.

## 9. Closed phrase sets

Event phrases (the only allowed `message.text`; WORKER adds phrases by plan amendment):
`attempt queued`, `worker process started`, `proposal bytes captured`,
`output streams digested`, `attempt evidence bound`, `cancellation requested`,
`workspace audit failed; proposal withheld`, `evidence retention state recorded`.

`runtime_state` phrases: `queued`, `running`, `cancelling`, `finished (completed)`,
`finished (cancelled)`, `finished (timed_out)`, `finished (failed_to_start)`, `refused`,
`unknown`, `stale_unknown`.

## 10. Python surface frozen by IF-0-JOURNAL-1

```text
# run_status.py (SL-0)
JOURNAL_FAMILY = "supervised_run_status.v1"; INDEX_SCHEMA = "phase_loop.supervised_admission_index.v1"
AttemptIdentity(assignment_digest, envelope_digest, run_id, attempt_id)        # frozen dataclasses
Units(target_unit_ids, readonly_neighbor_unit_ids, snapshot_ref)
WriterIdentity(harness_id, harness_version, writer_instance_id, owner_pid, process_start_time)
Ref(kind, sha256, locator); Termination(reason, signal, by); TerminalRefusal(reason, constraint, tier)
ResultBinding(envelope_digest, run_id, attempt_id, proposal_bytes_digest, evidence_envelope_digest)
Reservation(identity, units, index_seq, entry_sha256, writer); ChainHead(segment_index, segment_sha256, last_seq)
JournalLimits(...section 6...); DEFAULT_LIMITS; JournalRoot; JournalRefused(code)
AttemptRead(attempt_id, identity, units, writer, lines, state, terminal, chain_head, diagnostics, display)
IndexRead(assignment_digest, entries, head_sha256, diagnostics)
default_journal_root(environ: Mapping[str, str] | None = None) -> Path
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
resolve_run(root, run_id) -> tuple[str, ...] | JournalRefused        # attempt ids in index order

# run_status_projection.py (SL-1)
ProcessObserver = Callable[[int], tuple[bool, str | None]]; EvidenceResolver = Callable[[Ref], str]
ProjectionResult(projection, unknown_attempts, diagnostics); AttemptStatus(attempt_id, state, display,
  termination, refusal, result_binding, chain_head, diagnostics); PageResult(page, diagnostics)
project_assignment(root, assignment_digest) -> ProjectionResult
check_projection(projection: Mapping, root) -> tuple[str, ...]
attempt_status(root, attempt_id, *, observer: ProcessObserver = proc_observer) -> AttemptStatus
read_page(root, request: bytes, *, evidence: EvidenceResolver) -> PageResult | JournalRefused
check_page(request: Mapping, page: Mapping) -> tuple[str, ...]
build_reader_view(row: Mapping, status: AttemptStatus, *, work_outcome=None, evidence=None) -> Mapping | JournalRefused
check_reader_view(view: Mapping) -> tuple[str, ...]
proc_observer(pid: int) -> tuple[bool, str | None]
```

Names and signatures do not change during execution without a plan amendment. Records are
immutable. Exceptions from I/O or parsing are translated to closed codes `from None`.
Diagnostics and refusals carry codes only, never input values, paths or exception text.
`termination`, `refusal` and `result_binding` pass through `AttemptStatus` unchanged.

## 11. Consumer obligations

- **WORKER**: after `consume_admission`, call `reserve_attempt` before any chain spawn,
  and treat any `JournalRefused` as zero-invocation refusal. Keep reservation and writer
  in the launcher process that owns the leader. Emit only section 9 phrases. Build refs
  with `make_ref`. Put `ChainHead.last_seq` and `segment_sha256` from the terminal append
  into `--result` as the controller-held anchor. Use `process_start_identity` for the
  cancel-identity start time. Supply the `output_retention`-backed `EvidenceResolver`.
  Pass workspace, target and reference roots as `excluded`. Map `status --run|--attempt`
  to `resolve_run` / `attempt_status`. Never signal a pid or pgid read from a journal.
- **PLACECLI / LANEEXEC**: status reports `attempt_status`, whose display can be
  `unknown` or `stale_unknown` beyond LANEEXEC's queued/running/cancelling vocabulary.
  Per-client inventories use distinct roots. Attempt ids must fit section 3.
- **CLOSEOUT**: rerun the same vector harness and production entries under the v2 intake
  (same run-status bytes), and reconcile any local code that public v2 renames. The six v2
  `kind=echo` cases cannot pass echo bytes through the journal writer: journal lines have no
  `caller_context` member, and the roadmap allows only its digest. The index-held
  `caller_context_sha256` is the anchor. A dropped `__proto__` member or a changed number
  changes the JCS bytes, so the digest no longer matches. CLOSEOUT's "through the real
  JOURNAL writer" wording needs that reconciliation.

## 12. Vector ownership (all 35 `run-status.vectors.json` cases)

| Kind (count) | Production entry | Lane |
| --- | --- | --- |
| journal (19) | materialize to disk, then `read_index` + `read_attempt` | SL-0 |
| projection (4) | `project_assignment` / `check_projection` | SL-1 |
| liveness (3) | `attempt_status` with a vector-observation observer | SL-1 |
| reader_view (5) | `check_reader_view` and `build_reader_view` | SL-1 |
| page (4) | `check_page`; V-page also re-derived through `read_page` | SL-1 |

`tests/_run_status_vectors.py` (SL-0) loads the corpus through
`load_contract_bundle().resource_bytes`, applies the RFC 6902 add/remove/replace patches
with RFC 6901 pointers, asserts each edit took effect, and materializes `journal` inputs
to a temporary root. It writes an index entry per attempt in listed order, segments as
listed (an object line as JCS, a string line raw, a final LF unless
`final_newline: false`), and modes 0700/0600 under umask 077. It has no semantic logic,
and its output only enters production readers.

## 13. Named mutation controls

Use the ENVELOPE pattern (`tests/test_supervised_launch_mutations.py`). Each control
replaces exactly one asserted-present source fragment, execs the mutated module under a
temporary name, and makes a witness that passes on production fail. Controls live in the
owning lane's test file.

- SL-0: `index_lock`, `index_fsync`, `attempt_excl`, `run_claim`, `index_chain`,
  `index_torn_refusal`, `component_nofollow`, `owner_check`, `mode_check`, `nlink_check`,
  `torn_line`, `unknown_version`, `foreign_writer`, `seq_gap`, `segment_chain`,
  `missing_segment`, `identity_key`, `lifecycle_order`, `refused_after_launch`,
  `phrase_set`, `ref_digest_only`, `locator_rule`, `line_cap`, `reader_readonly`.
- SL-1: `index_order` (replace with lexical or mtime order), `latest_fallback`,
  `projection_behind`, `projection_ahead`, `owner_live`, `pid_reuse`, `page_bound`,
  `page_attempt_bound`, `omitted_counts`, `retention_count`, `cursor_binding`,
  `outcome_source`, `row_join`, `runtime_phrase_set`.
