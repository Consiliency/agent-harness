# v12 WORKER / landed JOURNAL sweep — 2026-11-09

This is one amendment of IF-0-WORKER-1, including the coordinator-approved
choice to return `unknown_attempt` before reading a launcher record when
JOURNAL returns no indexed identity. The two intake stops arose
from downstream assumptions surviving JOURNAL interface revisions. The sweep
covers the entire revision-4 WORKER contract before resealing revision 5; it
adds no implementation lane, acceptance criterion or public conformance claim.
The CLI contract now specifies root refusals and exposes page diagnostics. No design-choice STOP remains.

## Baseline and citation key

All contract line numbers below refer to revision 4 at the inspected input
`origin/main` commit `504355e020c271b649dd01e5f494c516d5164319`, so they remain
stable after this amendment. Code and schema line numbers use that same input.
MATCH means the original claim/call is compatible; MISMATCH includes an omitted
required boundary or an overbroad guarantee. Every MISMATCH is corrected in this
amendment; narrow factual clarifications are identified on MATCH rows.

- Contract: `plans/artifacts/v12-WORKER-contract.md`.
- R: `phase-loop-runtime/src/phase_loop_runtime/run_status.py`.
- P: `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`.
- S: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/run-status.schema.json`.
- E: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/admitted-launch-envelope.schema.json`.

The constructor signatures below list all required fields. A nullable field is
still required unless a default is explicitly given. WORKER-owned capture,
audit, filesystem and proposal mechanics (§2, §3.2–§3.3, §4–§6) were read in full;
only their JOURNAL/schema crossings are tabulated. They are not implemented by
JOURNAL and are not misclassified as missing JOURNAL APIs. The bundle's provenance
and conformance files introduce no additional WORKER-consumed Python calls.

## Full sweep table

| ID | Contract lines | Result | Claim / full consumed call or payload | Landed file:line evidence | Reconciliation |
| --- | --- | --- | --- | --- | --- |
| C01 | 8–13, 41–47, 657–666 | MATCH | Harness-local surface; SCHEMA labels provisional; deferred public reconciliation, no v1 envelope consumed at runtime. | R:118–248; S:4–5; E:4–5 | No public WORKER result schema is asserted. |
| C02 | 41–47 | MATCH | All imported JOURNAL types and functions exist in the stated modules. | R:118–248,817–825,898–930,1038,1165,1229,1415,1872; P:24–25,68–71,255,271,366 | No symbol rename needed. |
| C03 | 233–236, 383–393, 648–651 | MATCH | default_journal_root() -> Path uses pwd.getpwuid(os.geteuid()).pw_dir; WORKER state root plus journal. | R:817–822 | Environment-independent default agrees. |
| C04 | 233–236, 545, 649–651 | MISMATCH | open_journal_root(path: Path, *, create: bool, excluded: tuple[Path,...]=()) -> JournalRoot or JournalRefused. | R:825–887 | Launch creates; status and cancel pass create=False. A root refusal prints its code for status and gives unknown_attempt with zero signals for cancel; the original omitted those boundaries. |
| C05 | 231–236, 391–393 | MATCH | Trusted root, excluded workspace/target/reference roots, 0700 dirs/0600 files; journal outside retention root. | R:608–616,825–887,1130–1162,1262–1272 | WORKER keeps pruning outside journal; read-only open creates nothing. |
| C06 | 237–242, 628–630 | MATCH | reserve_attempt(root: JournalRoot, identity: AttemptIdentity, *, units: Units, launch_digest: str, caller_context_sha256: str) -> Reservation or JournalRefused. | R:1165–1205 | All three keyword-only arguments present. |
| C07 | 237–242, 589, 631 | MISMATCH | Reservation durability and zero-effects test claim. | R:1096–1205 | Successful claim durable and globally exclusive; failure can leave run/attempt claims or index bytes. Qualify J1 and W4; torn index/short run record blocks later reservation with index_unverifiable/run_record_unreadable until operator quarantine, and WORKER returns the code. |
| C08 | 237–242, 590 | MATCH | Duplicate/terminal/crash-reserved attempt refuses; retry uses new attempt id; run may have several attempts. | R:1038–1061,1130–1141,1186–1192 | Claim is never released by close; reservation failure means no spawn or further WORKER effects. |
| C09 | 240–242, 630 | MATCH | open_writer(root: JournalRoot, reservation: Reservation, *, limits: JournalLimits=DEFAULT_LIMITS) -> AttemptWriter or JournalRefused. | R:1415–1480 | Existing two-positional-argument call is valid; J1 now spells out optional limits for completeness. |
| C10 | 240–242, 637–639 | MATCH | open_writer retains reservation writer and refuses another process as writer_identity_mismatch. | R:1425–1439,1463 | PID and process-start binding agree. |
| C11 | 242, 251, 254, 632 | MATCH | state(self, state: str, *, worker_invocations: int) -> ChainHead or JournalRefused. | R:1324–1336 | queued=0, running=1, cancelling retains count; counts cannot decrease. |
| C12 | 254–255, 269–277, 632 | MATCH | event(self, phrase: str, *, refs=()) -> ChainHead or JournalRefused. | R:1338–1356 | Keyword-only refs; default empty tuple. |
| C13 | 278–289, 632 | MATCH | terminal(self, state: str, *, worker_invocations: int, termination: Termination or None, refusal: TerminalRefusal or None, result_binding: ResultBinding or None) -> ChainHead or JournalRefused. | R:1358–1399 | All four keyword-only fields supplied, including explicit None. |
| C14 | 284, 304–307, 635 | MATCH | close(self) -> None releases lock/descriptors; no append after failure. | R:1286–1291,1401–1412 | Idempotent; writer-local poisoning is not persisted or rolled back. |
| C15 | 405–412, 643–647 | MATCH | EvidenceResolver = Callable[[AttemptIdentity, Ref], str]. | P:25,34,358–364,423–431 | Only present, retention_dropped, unknown recognized; invalid return/exception becomes unknown. |
| C16 | 269–273, 654 | MATCH | make_ref(kind: str, data: bytes, locator: str or None) -> Ref. | R:913–918 | None locator accepted; digest of bytes only, invalid input raises ValueError. |
| C17 | 455, 489, 638 | MATCH | process_start_identity(pid: int) -> str or None. | R:898–910 | Boot id + start ticks; dead/zombie/unreadable returns None; verification fails closed. |
| C18 | 452, 470, 486–487, 553, 639–641 | MISMATCH | read_attempt(root: JournalRoot, attempt_id: str) -> AttemptRead; identity and writer assumed always available. | R:236–248,1486–1489,1872–1890 | Identity/writer can be None together; guard page dereference. Coordinator chooses unknown_attempt on the first cancel look, before any launcher-record read or signal; indexed unknown reads may still retain identity/writer. |
| C19 | 471–472, 550–551, 640 | MATCH | resolve_run(root: JournalRoot, run_id: str) -> tuple[str,...] or JournalRefused. | R:1038–1061 | Absent run (), otherwise index order; taking last id selects latest for run. |
| C20 | 470, 477–478, 548–549, 641–642 | MISMATCH | attempt_status(root, attempt_id: str, *, observer=proc_observer) -> AttemptStatus; J4 states dead/reused owner always stale_unknown. | P:271–290 | Only verified nonterminal consults liveness; qualify J4. Terminal check in cancel already comes first. |
| C21 | 548–549, 642 | MATCH | proc_observer(pid: int) -> tuple[bool, str or None]. | P:255–268; R:898–910 | Default observer is provider-free; missing/malformed observer result is not live. |
| C22 | 552–557, 643–646 | MISMATCH | read_page(root, request: bytes, *, evidence: EvidenceResolver) -> PageResult or JournalRefused. | P:366–386,433–441 | Encode UTF-8 JSON bytes, handle refusal, guard missing identity; original omits byte boundary and refusal return. |
| C23 | 555–557, 645–646 | MISMATCH | page_request required assignment_digest, page_size, cursor; J5 gives only upper bound. | P:297–303,366–386; S:502–527 | Require integer 1..100, cursor string or null; next_cursor nullable. CLI's 50 already valid. |
| C24 | 646–647 | MISMATCH | omitted.retention_dropped described without returned-page scope. | P:423–434 | Counts dropped refs in selected returned events, not all retained history; qualify J5. |
| F01 | 160–166, 237 | MATCH | AttemptIdentity has assignment_digest, envelope_digest, run_id, attempt_id, all required non-null. | R:118–122,518–520; S:21–48 | Two SHA-256 digests; local id grammar 1..128. WORKER's launch/raw digests are not passed as extra journal identity fields. |
| F02 | 164–165, 237 | MATCH | Units(target_unit_ids, readonly_neighbor_unit_ids, snapshot_ref) required non-null. | R:126–129,523–535; S:50–80 | Nonempty target list, neighbors may be empty; snapshot SHA-256. Local snapshot_reference is mapped, not a claim about v1 envelope member names. |
| F03 | 163, 226–229, 238, 439, 600 | MATCH | launch_digest and caller_context_sha256 supplied as required digest strings at reservation; caller context content stays out of journal. | R:215–223,1165–1197; E:153–156 | JCS-hashed caller context; local index fields, not extra public journal-line keys. |
| F04 | 449–452, 459–461, 486–487, 636–639 | MATCH | WriterIdentity required harness_id, harness_version, writer_instance_id, owner_pid, process_start_time; nonce random 128-bit lowercase hex. | R:133–138,538–541,926–930,1245–1249; S:82–121 | Minted once; every line copies writer identity; nonce is not authentication. |
| F05 | 449–452, 628–639 | MATCH | Reservation contains identity, units, index_seq, entry_sha256, writer; successful reservation non-null. | R:172–177,1205 | writer is required in Reservation, unlike unknown AttemptRead. |
| F06 | 179–182, 284, 633 | MATCH | ChainHead(segment_index, segment_sha256, last_seq); anchor uses last_seq and current segment digest. | R:181–184,1283–1284,1312–1322 | Returned only after successful append/fsync; reader-derived chain head is not controller-held append acknowledgment. |
| F07 | 188–194, 278–282, 288–289 | MATCH | WorkerResult state finished/refused; termination nullable only for refusal; journal flags and anchor are local result fields. | R:227–233,1358–1399; S:304–443 | No attempt to put WORKER result fields into closed journal body. |
| F08 | 85–87, 115–119, 278–282 | MATCH | Termination(reason, signal, by): completed/cancelled/timed_out/failed_to_start; worker/harness/operator; signal nullable. | R:66–67,149–152,1367–1370; S:329–367 | Exit code, duration, streams and invocation details in capture/evidence are local, not extra Termination members. |
| F09 | 278–282, 288–289 | MATCH | TerminalRefusal(reason, constraint, tier): nonempty reason; nullable constraint/tier; refused termination and binding None, invocations zero. | R:156–159,1372–1375; S:368–401 | Healthy refusal only from queued. |
| F10 | 261–267, 278–283, 592 | MATCH | ResultBinding(envelope_digest, run_id, attempt_id, proposal_bytes_digest, evidence_envelope_digest); binding nullable, proposal digest nullable, evidence digest required when binding exists. | R:163–168,1376–1392; S:402–443 | Revision 4 fix matches: evidence error passes None binding even on completed terminal; no evidence refs. |
| F11 | 269–273, 417–418, 654 | MATCH | Ref(kind, sha256, locator): all fields required; locator nullable/repo-relative. | R:64–65,142–145,913–924; S:123–156 | WORKER uses evidence_envelope/proposal_bytes and None locator; digest never inline data. |
| F12 | 405–415, 597 | MATCH | Retention resolution keyed by attempt plus ref; unrecorded deletion unknown; equal proposal bytes across attempts legitimate. | P:358–364,423–434; R:1817–1828; S:756 | Unknown produces evidence_unknown diagnostic; dropped preserves journal digest and contributes omitted count. |
| F13 | 545–559 | MISMATCH | PageResult(page: dict, next_cursor: str or None, diagnostics: tuple[str,...]); page events/has_more/omitted. | P:68–71,306–322,433–441; S:529–580 | CLI outer next_cursor and page_diagnostics are local fields, not added public page keys. Preserve PageResult.diagnostics: an attempt with diagnostics contributes no events (P:402–404); omitted counts do not replace those codes. |
| E01 | 269–270 | MATCH | attempt evidence bound with one evidence_envelope ref, omitted on withheld_evidence_error. | R:54–64,1338–1356; S:244–278 | event body includes untrusted_display_text message and refs array. |
| E02 | 271–272 | MATCH | proposal bytes captured with one proposal_bytes ref only when returned. | R:54–64,1338–1356; S:244–278 | Exact closed phrase and valid ref kind. |
| E03 | 273–274 | MATCH | workspace audit failed; proposal withheld, refs empty, for audit/unexplained-change withholding. | R:54–64,1338–1356 | Exact phrase allowed. |
| E04 | 275–277, 653–654 | MATCH | proposal withheld with no refs for other withheld statuses; absent emits no withholding event. | R:54–64,1338–1356 | Exact phrase allowed; no mandatory event for absent. |
| E05 | 254–255, 463–465 | MATCH | cancellation requested, refs empty, after cancelling state and before own-group kill. | R:54–64,1338–1356; R:108–113 | Valid event between cancelling and finished; signal operation is WORKER-owned. |
| L01 | 242–255, 288–290 | MATCH | queued -> running -> cancelling? -> finished; queued -> refused; refusal never follows start. | R:103–113,1293–1294,1324–1336,1358–1375,1698–1718; S:726–740,757–758 | A failed exec after successful running is finished/failed_to_start, not refused. |
| L02 | 251–255, 589 | MATCH | Successful running append before spawn; no spawn on append refusal; cancelling preserves invocations. | R:1312–1336 | WORKER order is stricter caller policy compatible with JOURNAL; running can be readable although no worker spawned. |
| L03 | 268–284 | MATCH | Evidence events precede terminal; terminal is last; anchor only from successful terminal append, then close. | R:1338–1343,1358–1399,1689–1690 | Reader rejects later lines; JOURNAL does not create WORKER evidence files. |
| L04 | 292–307, 632–635 | MATCH | Rule W stops after open_writer/state/terminal refusal, non-cap event refusal or exception; later poisoned writer calls refuse. | R:1286–1291,1312–1317,1324–1327,1338–1341,1358–1363 | WORKER is deliberately stricter than writer poisoning: validation refusals need not poison JOURNAL. |
| L05 | 301–307 | MATCH | Partial append may be torn; event_cap_reached drops event and reserves terminal capacity. | R:1296–1317,1769–1796; S:750 | Nonterminal cap leaves two slots (possible rotated header + terminal); a state cap refusal still triggers Rule W. |
| L06 | 309–320 | MISMATCH | All failures described as unknown or stale_unknown, including complete failed-fsync terminal. | R:1312–1317,1401–1412,1754–1831; P:271–290 | A complete verified queued/running/cancelling line displays itself while live, stale_unknown after exit/reuse. A refused or `finished (<reason>)` terminal retains its display regardless of liveness; refused may retain a reason different from WORKER journal_unavailable. Torn/unverifiable or no-state history is unknown. Reader chain_head/display never replaces the missing anchor; poisoning stays writer-local. |
| L07 | 309–316 | MATCH | Before-spawn failure returns local refused/journal_unavailable; after-spawn returns local finished with observed termination; both no anchor and journal_complete=False. | R:1312–1322; P:271–290 | WORKER result does not relabel journal replay; controller must use acknowledgment uncertainty. |
| L08 | 318–320 | MISMATCH | Missing anchor uncertainty statement omits runtime/work-outcome distinction alongside false replay guarantee. | P:447–462; S:763–765 | Retain uncertainty and explicitly name runtime_not_work_outcome; completion display never proves work success. |
| L09 | 589 | MISMATCH | W4 expects stale_unknown immediately for a landed-then-failed running append. | P:271–290 | W4 covers queued failure, running landed then failed (no spawn; live running, exited/reused stale_unknown), healthy-writer refused landed then failed (original JOURNAL reason; WORKER journal_unavailable), and all finished reasons regardless of liveness; torn history unknown. Failure still gives no anchor and journal_complete=False. |
| L10 | 449–502 | MATCH | Cancel checks terminal before liveness, then stale nonterminal; dead/reused nonterminal means owner_not_live with zero signals. | P:277–290; R:898–910 | Terminal finished(cancelled) or refused(cancelled_before_start) maps to cancelled after wait; other terminal already_terminal; no terminal cancel_pending. |
| L11 | 470–505 | MATCH | CancelOutcome values are WORKER-local, not JOURNAL states; pidfd/live-record validation must precede signal. | P:51–64,271–290; R:133–138 | unknown_attempt, owner_unverified, owner_not_live are cancellation outcomes; no JOURNAL signaling API is asserted. |
| L12 | 545–559, 598, 619 | MATCH | Status uses attempt_status and its default liveness observer; closed runtime display values, provider-free. | P:31–34,255–290 | Do not substitute read_attempt.display or project_assignment state for liveness-aware display. |
| L13 | 318–320, 641–642 | MISMATCH | Generic reader/projection guarantee conflates replay state with liveness-aware display. | P:119–147,209–230,271–290; R:1872–1890 | Raw read/projection remain replay-derived; only attempt_status checks nonterminal owner. Complete failed-fsync lines remain eligible for replay/projection. |
| L14 | 436–443, 565–568, 663–666 | MATCH | Evidence/result version-0 labels, exit codes and WORKER proposal statuses are harness-local and deferred. | S:5,304–443,582–719; E:4–5 | No v1 schema requirement is imposed on local ProposalReturn, CancelOutcome or result record. |
| L15 | 570–600, 602–619 | MATCH | Real-writer fault injection, caller-context digest test, retention/cancel/CLI obligations and mutations use consumed seams. | R:1165–1205,1296–1317,1338–1399; P:271–290,358–441 | W4 corrected above; other obligations compatible. This sweep is static evidence, not execution of W1–W15. |

## Failure/read matrix

The matrix assumes any surviving complete history passes the reader's structural,
chain, identity and provenance checks. Other diagnostics make it unknown.

| Append outcome | Live owner | Exited/reused owner | WORKER acknowledgment |
| --- | --- | --- | --- |
| No new bytes, earlier valid nonterminal remains | Earlier state | stale_unknown | No anchor; journal_complete=False |
| Full queued/running line, fsync fails | queued/running | stale_unknown | No spawn; refused/journal_unavailable; no anchor; journal_complete=False |
| Full cancelling line, fsync fails | cancelling | stale_unknown | finished with observed termination; no anchor; journal_complete=False |
| Full refused terminal, fsync fails | refused (original reason) | refused (original reason) | refused/journal_unavailable; no anchor; journal_complete=False |
| Full finished terminal, fsync fails | `finished (<reason>)` | `finished (<reason>)` | finished with observed termination; no anchor; journal_complete=False |
| Torn/malformed final history | unknown | unknown | No anchor; journal_complete=False |
| No verifiable state (for example missing journal or header only) | unknown | unknown | No anchor; journal_complete=False |

`read_attempt` and `project_assignment` replay bytes; their state is not a
liveness-aware display. `attempt_status` checks liveness only after excluding
unknown and terminal reads. A reader-derived chain head cannot replace the
controller's missing successful terminal-append anchor. None of these statuses
is a work outcome (`runtime_not_work_outcome`).

## JOURNAL follow-up

The deferred JOURNAL decision is filed as
[agent-harness#1954](https://github.com/Consiliency/agent-harness/issues/1954):
specify reader semantics for a complete line whose append was not acknowledged.
JOURNAL can document the current behavior or define a reader-visible marker,
including restart, read-only-filesystem and reader-compatibility semantics.
This does not block WORKER intake: the missing controller-held anchor plus
`journal_complete=False` retains uncertainty. This amendment changes no JOURNAL
code or schema.

## Exact old and new text

Every changed sentence is included below, with unchanged surrounding context
so each passage can be reviewed in full. Old line numbers refer to the inspected
revision 4 input; new numbers refer to revision 5 after the single review round.

### plans/artifacts/v12-WORKER-contract.md

Old lines 15–23; new lines 15–26:

Old:

```text
Revision 2 applies the agent-harness#1926 board edits and the owner rulings
recorded in the plan's Context (2026-11-08). Revision 3 reconciles §3–§8 with
JOURNAL's revised §10/§11 (agent-harness#1925 at 86d11deda7bbb1088b9cb1e300064c34f52c71e6,
an input pin). Revision 4 (2026-11-09) reconciles the evidence-error terminal
binding with landed JOURNAL (agent-harness#1934).

## 1. Consumed interfaces

Pre-existing, landed, and not edited by WORKER:
```

New:

```text
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
```

Old lines 314–324; new lines 317–337:

Old:

```text
- After spawn: the capture, audit and evidence steps complete. Return
  `state=finished` with the capture's termination, `journal_anchor=None` and
  `journal_complete=False`.

In both cases JOURNAL reports the attempt `unknown` or `stale_unknown`; WORKER
never relabels it. A missing anchor is the controller's signal to treat the
outcome as uncertain.

Descriptor execution (ELF through an inherited fd path) is used where
supported. Otherwise evidence records `exec_binding: "path_recheck"` and
readiness discloses the remaining check-to-exec window.
```

New:

```text
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
```

Old lines 448–456; new lines 461–473:

Old:

```text

1. takes its nonce from `Reservation.writer.writer_instance_id`. That value is
   128-bit random lowercase hex, minted once by `reserve_attempt` and copied
   unchanged by `open_writer` (J3). A later cancel reads it from
   `read_attempt(root, attempt_id).writer`;
2. at step 4 creates `launchers/<attempt_id>.json` with
   O_CREAT|O_EXCL|O_NOFOLLOW, mode 0600, holding {run_id, attempt_id,
   assignment_digest, pid, process_start_time (`process_start_identity(pid)`),
   exe_realpath, exe_sha256, cmdline_sha256, nonce};
```

New:

```text

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
```

Old lines 464–479; new lines 481–499:

Old:

```text
`cancelled_before_start`. While running, the launcher journals `cancelling`,
then the capture kills only its own group. A cancel arriving between
reservation and record creation finds no record and returns `owner_unverified`.

`cancel_attempt` resolves the target as follows:

- `--attempt` reads `read_attempt` and `attempt_status`;
- `--run` takes the last id from `resolve_run`. An absent run, which returns
  `()`, or a `JournalRefused` gives `unknown_attempt`.

On the first look, the outcome is:

- already terminal: `already_terminal`;
- `attempt_status` display `stale_unknown` (dead or reused owner):
  `owner_not_live`, with zero signals;
- otherwise, verification proceeds.
```

New:

```text
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
```

Old lines 541–559; new lines 561–583:

Old:

```text
  - `open_result_file(path: Path, *, excluded: tuple[Path, ...]) -> int | Refused`
    requires an absolute path with a verified 0700 operator parent opened by
    dir_fd. It opens O_CREAT|O_EXCL|O_NOFOLLOW with mode 0600, outside the
    workspace, target, reference roots and state root.
- `status` is provider-free. It opens the journal root without creating it and
  prints one JSON object `{"attempt": <attempt_status>, "page": <page | null>,
  "next_cursor": <str | null>}`:
  - `--attempt` uses `attempt_status(root, id)`, with JOURNAL's liveness
    observer;
  - `--run` uses the last id from `resolve_run`. An absent run (`()`) or a
    refusal prints `unknown_attempt` and exits as a refusal;
  - `--page` adds `read_page` with the request `{assignment_digest:
    read_attempt(root, id).identity.assignment_digest, page_size:
    STATUS_PAGE_SIZE, cursor}` and `evidence=evidence_resolver(state_root)`.
    The output then includes `next_cursor`;
  - `--cursor` passes a `next_cursor` from a previous page; otherwise `cursor`
    is null.
  - `STATUS_PAGE_SIZE = 50`, within JOURNAL's bound of 100.
  Display text comes only from JOURNAL's closed phrase sets.
```

New:

```text
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
```

Old lines 585–593; new lines 609–617:

Old:

```text
| --- | --- | --- | --- |
| W1 | SL-0 | Capture: stdout/stderr digests over all bytes, cap + overflow, stdin one-shot and not in argv, deadline, cancel, group reclaim, failed start, `before_spawn` refusal = zero spawns; a pipe-holding escaped descendant ends at the deadline with `streams_complete=False` | EC-WORKER-1, EC-WORKER-4 |
| W2 | SL-0 | `run_bounded` parity: every existing status/detail/bound unchanged | EC-WORKER-1 |
| W3 | SL-0 | Planted `SSH_AUTH_SOCK`, `GIT_ASKPASS`, `SSH_ASKPASS`, `GIT_CONFIG_*` credential-helper, vendor and GH tokens absent from the child; empty default allowlist passes only scratch names | EC-WORKER-4 |
| W4 | SL-1 | Order §3.1: zero invocations and zero attempt effects for every refusal at steps 1–3; healthy-writer refusals journal `refused` from `queued`; Rule W for a failing `queued`, a `running` append that lands then fails (no spawn, `stale_unknown`), and a post-spawn terminal failure (`finished`, no anchor) | EC-WORKER-2, EC-WORKER-4 |
| W5 | SL-1 | Replay one envelope sequentially, concurrently across 4 processes, and after a crash between reservation and spawn: at most one spawn in total; a retry under the same run with a new attempt id launches | EC-WORKER-2, EC-WORKER-3, EC-WORKER-4 |
| W6 | SL-1 | Pre-spawn recheck of each identity element | EC-WORKER-2 |
| W7 | SL-1 | Proposal decision table, every row including `streams_complete=False` and `withheld_evidence_error` (fault each step-9 operation; real JOURNAL accepts `finished` with unchanged termination and null binding, no evidence refs, no proposal digest or locator, and no readable valid result even with partial files); baselines; malformed and oversized | EC-WORKER-1, EC-WORKER-4 |
| W8 | SL-1 | Audit: workspace change per tier, target change, ref change, gitfile escape, cap and special-file errors | EC-WORKER-1, EC-WORKER-4 |
```

New:

```text
| --- | --- | --- | --- |
| W1 | SL-0 | Capture: stdout/stderr digests over all bytes, cap + overflow, stdin one-shot and not in argv, deadline, cancel, group reclaim, failed start, `before_spawn` refusal = zero spawns; a pipe-holding escaped descendant ends at the deadline with `streams_complete=False` | EC-WORKER-1, EC-WORKER-4 |
| W2 | SL-0 | `run_bounded` parity: every existing status/detail/bound unchanged | EC-WORKER-1 |
| W3 | SL-0 | Planted `SSH_AUTH_SOCK`, `GIT_ASKPASS`, `SSH_ASKPASS`, `GIT_CONFIG_*` credential-helper, vendor and GH tokens absent from the child; empty default allowlist passes only scratch names | EC-WORKER-4 |
| W4 | SL-1 | Order §3.1: zero invocations for every refusal at steps 1–3, zero attempt effects at steps 1–2, and no further WORKER effects after a reservation refusal (failed reservation may leave JOURNAL claims); healthy-writer refusals journal `refused` from `queued`; Rule W for a failing `queued`, a `running` append that lands then fails (no spawn, `running` while the owner is live, `stale_unknown` after owner exit or pid reuse), a healthy-writer `refused` terminal that lands then fails (WORKER `refused`/`journal_unavailable`; JOURNAL keeps `refused` with the original reason), and a post-spawn terminal failure (WORKER `finished`, no anchor, `journal_complete=False`; a complete terminal keeps `finished (<reason>)` after owner exit or pid reuse; torn history displays `unknown`) | EC-WORKER-2, EC-WORKER-4 |
| W5 | SL-1 | Replay one envelope sequentially, concurrently across 4 processes, and after a crash between reservation and spawn: at most one spawn in total; a retry under the same run with a new attempt id launches | EC-WORKER-2, EC-WORKER-3, EC-WORKER-4 |
| W6 | SL-1 | Pre-spawn recheck of each identity element | EC-WORKER-2 |
| W7 | SL-1 | Proposal decision table, every row including `streams_complete=False` and `withheld_evidence_error` (fault each step-9 operation; real JOURNAL accepts `finished` with unchanged termination and null binding, no evidence refs, no proposal digest or locator, and no readable valid result even with partial files); baselines; malformed and oversized | EC-WORKER-1, EC-WORKER-4 |
| W8 | SL-1 | Audit: workspace change per tier, target change, ref change, gitfile escape, cap and special-file errors | EC-WORKER-1, EC-WORKER-4 |
```

Old lines 619–635; new lines 643–661:

Old:

```text
  check, each result-open flag, status liveness source.

## 8. JOURNAL interfaces consumed (J1–J6)

These are reconciled with JOURNAL's revised §10 and §11 at agent-harness#1925
head 86d11deda7bbb1088b9cb1e300064c34f52c71e6, an input pin. The work-start
gate re-checks them against the landed code. A later rename is a WORKER artifact
amendment, not an in-lane workaround.

- J1 — `reserve_attempt(root, identity, *, units, launch_digest,
  caller_context_sha256) -> Reservation | JournalRefused` and
  `open_writer(root, reservation) -> AttemptWriter | JournalRefused`. The
  reservation is atomic, durable and claims the attempt id globally.
- J2 — `AttemptWriter.state`, `.event`, `.terminal` and `.close`. Appends
  return `ChainHead(segment_index, segment_sha256, last_seq)` or
  `JournalRefused`. Any I/O failure poisons the writer: later calls refuse
  `writer_poisoned`, and `close()` only releases the lock (Rule W).
```

New:

```text
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
```

Old lines 638–651; new lines 664–682:

Old:

```text
  `writer_identity_mismatch` in another process. `process_start_identity(pid)`
  is importable, and `read_attempt(...).writer` returns the identity later.
- J4 — `resolve_run`, which returns `()` for an absent run; `read_attempt`,
  whose `.identity.assignment_digest` is the page key; and `attempt_status`
  with `proc_observer` liveness (`stale_unknown` for a dead or reused owner).
- J5 — `read_page(root, request, *, evidence)`, with
  `EvidenceResolver = Callable[[AttemptIdentity, Ref], str]` and a
  `page_request` of `{assignment_digest, page_size <= 100, cursor}`. It returns
  `PageResult(page, next_cursor, diagnostics)`; `omitted.retention_dropped`
  counts refs the resolver reports dropped.
- J6 — `default_journal_root()`, with no arguments, from `pw_dir`, equals
  `<default_state_root()>/journal`. `open_journal_root(path, *, create,
  excluded)` takes WORKER's `<state_root>/journal`, outside every
  output_retention root.
```

New:

```text
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
```

### plans/phase-plan-v12-WORKER.md

Old lines 94–104; new lines 94–104:

Old:

```text

## External Inputs

- Frozen contract: `plans/artifacts/v12-WORKER-contract.md`, sealed by this
  manifest amendment row `v12-WORKER-amend-withheld`'s `frozen_inputs`
  digest (sha256:
  `2b9c1f95308fe517a3897f85acca1c3b2d7ba52aa9060060b5a8afa65be1b95b`). It holds every exact signature,
  ordering rule, proposal/audit/cancel rule, test obligation W1–W15, mutation
  list and the JOURNAL names consumed. Read it in full before any lane starts.
  This plan points at it and does not repeat it.
- Landed IF-0-ENVELOPE-1 symbols and IF-0-SCHEMA-1 receipt rows on main.
```

New:

```text

## External Inputs

- Frozen contract: `plans/artifacts/v12-WORKER-contract.md`, sealed by this
  manifest amendment row `v12-WORKER-amend-journal-sweep`'s `frozen_inputs`
  digest (sha256:
  `222c6c07695f91e7bbaf47c5ff5fbc4590b4b677d6c31a4885d67646146da523`). It holds every exact signature,
  ordering rule, proposal/audit/cancel rule, test obligation W1–W15, mutation
  list and the JOURNAL names consumed. Read it in full before any lane starts.
  This plan points at it and does not repeat it.
- Landed IF-0-ENVELOPE-1 symbols and IF-0-SCHEMA-1 receipt rows on main.
```

## Seal

Revision 5 contract SHA-256: `222c6c07695f91e7bbaf47c5ff5fbc4590b4b677d6c31a4885d67646146da523`.

Manifest row: `v12-WORKER-amend-journal-sweep`. Historical rows are unchanged.

## Initial validation on dev0

Checks used the checkout source via absolute `PYTHONPATH` and the installed
`/home/viperjuice/.local/share/consiliency/agent-harness/tools/phase-loop-runtime/bin/python`.
Host load/IO and memory/cgroup headroom were inspected; all checks were serial
and bounded. No whole suite, Gate A, provider qualification or fault-injection
run was dispatched for this amendment.

| Check | Result |
| --- | --- |
| `timeout 120 python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v12-WORKER.md` | PASS: 3 lanes; existing warning (N), release-shaped plan without post-dispatch evidence-reducer lane |
| `plan_pin_lint.find_plan_pin_violations` on `plans/phase-plan-v12-WORKER.md` | PASS: 0 findings (module exposes a Python API, no CLI entrypoint) |
| `timeout 120 python -m phase_loop_runtime.plan_manifest check --repo .` | PASS: canonical=67, registered=67, unregistered=0 |
| `timeout 900 python -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_legible_roadmap_contract.py` | FAIL: 63 passed, 1 failed in 40.39s |
| `validate_plan_dispatch_hints` before writing the plan | PASS: no findings |
| `git diff --check` | PASS |

The failing node is
`test_assumption_probe_mutation_and_positive_control[LEGIBLE-A3-REVIEWTRUTH-TRANSITION]`.
Its synthetic mutation and positive control reach the final live-check arm;
that arm returns `ProbeFinding(code='observation_unavailable', detail='authority_missing')`.
The assertion at `phase-loop-runtime/tests/test_legible_roadmap_contract.py:1934`
requires the live verdict to be OK. This is a recorded test failure, not an
interruption or a pass. The test, roadmap and runtime sources it consumes are
unchanged by this amendment; no authority configuration was changed to satisfy
it. The suite also emitted `ContractFloorUnverified` from its installed-contract
check. Draft PR closeout reports both limitations. These are the initial amendment results; no merge or readiness claim is made.
The subsequent review confirmed the same `authority_missing` failure on the
inspected main input and the initial PR head in the non-Claude environment.

## Validation after the single review round

All six edits were applied, including the coordinator-approved `unknown_attempt`
choice before any launcher-record read. The paragraph, W4, root-refusal text,
nullable-identity text, page diagnostics and J1 sentence were checked against
the supplied replacements. The four requested checks were rerun on dev0:

- `validate_plan_doc.py`: PASS, 3 lanes, existing warning (N).
- `plan_pin_lint.find_plan_pin_violations`: PASS, 0 findings.
- `plan_manifest check`: PASS, canonical=67, registered=67, unregistered=0.
- `git diff --check`: PASS.

The contract seal agrees with the plan, this report and the single unmerged
amendment row. All manifest rows from the inspected main input remain unchanged.
The initial test-file result above remains recorded; that file was not rerun for
these documentation edits. No further review round was dispatched. Coordinator
confirmation and merge remain outside this amendment's closeout authority.
