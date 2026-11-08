---
phase_loop_plan_version: 1
phase: JOURNAL
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5
automation:
  suite_command: ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "phase-loop-runtime/tests", "-k", "test_run_status.py or test_run_status_projection.py or test_run_status_receipt.py or test_seat_reference_inventory.py"]
---

# JOURNAL: Attempt journal and projection

## Context

This is the second v12 seam phase for agent-harness#1818. It is the upstream
gate for WORKER and, through IF-0-JOURNAL-1, for v13 PLACECLI and LANEEXEC. The
roadmap EC IDs are the only acceptance authority. The roadmap stays
advisory/non-selectable, and v11 stays active. Manual authoring may start now
(Execution Notes: "ENVELOPE and JOURNAL may be planned and implemented now"),
but automatic phase-loop execution needs a separate lifecycle decision. This
planning PR authorizes no implementation, delegation, merge or live use.

**Key input finding.** The run-status family needs no synthetic labels. The
SCHEMA phase vendored `run-status.schema.json` and
`conformance/run-status.vectors.json`. Their bytes are identical at the v1 pin,
at the CLOSEOUT v2 pin and at the v13 `x-contract-pins.run_status` pin
(`plans/artifacts/v12-JOURNAL-interface.md` §1). JOURNAL therefore implements
against the pinned enums, required fields, `x-journal-rules`,
`x-semantic-rules` and `x-canonicalization`. It runs all 35 run-status vectors
through production paths as early reconciliation evidence. CLOSEOUT still
discharges authoritative acceptance (roadmap Execution Notes). The publisher
status is `provisional`.

Existing code inspected:

- `convergence/event_log.py` provides the durability discipline to reuse:
  dir_fd/O_NOFOLLOW opens, `flock`, full writes and file/directory `fsync`.
  Its torn-tail `ftruncate` repair must **not** be reused.
- `convergence/status.py` is the replay-only projection pattern to reuse.
- `output_retention._directory`/`_locked` show uid/mode and lock checks.
- `supervised_contracts.load_contract_bundle`/`validate_record` already validate
  `journal_line`, `projection`, `page_request`, `page` and `reader_view`.
- `rfc8785` is already a runtime dependency.
- `supervised_launch.consume_admission` keeps its single-use token only
  in-process. JOURNAL supplies the durable cross-process reservation.

No `run_status*.py` module, `test_run_status*.py` file or
`docs/supervised-run-status.md` exists yet.

The CLOSEOUT inputs artifact names `tests/test_run_status.py` and
`tests/test_run_status_projection.py` in its authoritative V2 group. Mutation
controls therefore live inside those two files, not in separate mutation
files, so CLOSEOUT's suite keeps exercising them.

## External Inputs

These inputs are vendored by SCHEMA, verified byte-identical at both public
consiliency-contract pins, and read-only in this phase:

- `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/run-status.schema.json`,
  sha256 `5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30`.
- `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/conformance/run-status.vectors.json`,
  sha256 `5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730`.

The frozen interface artifact `plans/artifacts/v12-JOURNAL-interface.md` is
sealed by SHA-256 in this plan's manifest `frozen_inputs`, and it governs the
details this plan only summarizes. The frontmatter hash pins the existing
roadmap. No future implementation SHA, commit count or landing topology is
pinned. Changed input bytes require a reviewed reseal.

## Interface Freeze Gates

- [ ] IF-0-JOURNAL-1 — `run_status.py` exports `reserve_attempt`,
  `open_writer`/`AttemptWriter` (`state`, `event`, `terminal`, `close`),
  `read_attempt`, `read_index`, `resolve_run`, `open_journal_root`,
  `default_journal_root`, `process_start_identity`, `make_ref` and the immutable
  records listed in the artifact. `run_status_projection.py` exports
  `project_assignment`, `check_projection`, `attempt_status`, `read_page`,
  `check_page`, `build_reader_view`, `check_reader_view` and `proc_observer`.
  The exact signatures, storage layout, admission-index format, reservation
  ordering, diagnostic map, caps, cursor and closed phrase sets are in
  `plans/artifacts/v12-JOURNAL-interface.md` §2–§10. Evidence:
  `plans/evidence/supervised-worker/JOURNAL.md`.

These are harness-local Python APIs. Public records are exactly the pinned
run-status definitions. The admission index, local diagnostic codes, cursor and
caps are harness-local, labelled as such, and never enter a public record.
`reserve_attempt` is the durable reservation for EC-WORKER-2: it is atomic under
the per-assignment lock, fsynced before return, and claims the attempt id
globally with an O_EXCL directory. Duplicate, terminal and crash-reserved ids
cannot be reused. Readers never repair, truncate or create files, and any
diagnostic makes the display `unknown`. A non-terminal attempt whose recorded
owner is dead, or whose pid was reused, reports `stale_unknown`, never
`running`. `caller_context` enters only as `caller_context_sha256` in the index.
Names do not change during execution without a plan amendment.

## Lane Index & Dependencies

SL-0 — Durable journal writer, admission index and verifying reader
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Replay projection, liveness, bounded pages and reader view
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Documentation, evidence and receipt reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Durable journal writer, admission index and verifying reader

- **Scope**: Build the locked single-writer journal, the durable per-assignment admission index and the fail-closed reader over the pinned line format.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_status.py`, `phase-loop-runtime/tests/test_run_status.py`, `phase-loop-runtime/tests/_run_status_vectors.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `reserve_attempt`, `open_writer`, `AttemptWriter`, `read_attempt`, `read_index`, `resolve_run`, `open_journal_root`, `default_journal_root`, `process_start_identity`, `make_ref`, `_run_status_vectors`, `SL-0 results` (signatures in artifact §10; harness in §12)
- **Interfaces consumed**: `load_contract_bundle` (pre-existing), `validate_record` (pre-existing), `rfc8785` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Build `_run_status_vectors.py` per artifact §12. In
    `test_run_status.py`, run every `kind=journal` vector through
    `read_index`/`read_attempt` with exact diagnostic sets and display effects.
    Add local cases:
    - Storage trust: wrong owner, group/world modes, symlinked components,
      hardlinked segments, non-regular entries, unexpected entries, a root
      inside an `excluded` root, and invalid single-component ids.
    - Reader integrity: missing journal, missing segment and unindexed attempt
      (display `unknown`), plus identity-versus-directory/index mismatch.
    - Writer rules: every lifecycle violation, the event cap with terminal
      headroom, rotation chaining across segments, and a non-phrase message.
    - Writer ownership: refusal of a second writer, a resumed writer and a
      writer in a different process. Reader runs leave every byte, mode and
      mtime unchanged.
    - Reservation: refuses duplicate, terminal, cross-assignment and
      crash-reserved ids, and refuses on a torn or broken index. Run real
      `sys.executable -I` subprocess races where N processes reserve one
      attempt id: exactly one wins. Kill a reserving child after the
      directory claim and before the index append, then show the id can
      never be reused and reads as `attempt_unindexed`.
    - Durability: an `os.fsync` spy proves the index and directory fsyncs
      happen before `reserve_attempt` returns.
    - Secrecy: plant prompt, source, secret and argv sentinels in bytes passed
      to `make_ref`, then scan every byte under the root to show they are
      absent and only digests appear. Tests pin umask 077 and set unsafe modes
      explicitly with `chmod`.
  - impl: Implement artifact §2–§7 and §9. Reuse the event_log durability
    pattern without its truncation. Validate every line produced and consumed
    with `validate_record(..., definition="journal_line")` before the semantic
    rules run. Derive writer identity from the current process, and refuse
    `liveness_unsupported` where `/proc` start identity is unavailable. Map I/O
    and parse exceptions to closed codes `from None`; diagnostics carry no
    values or paths. Add exact `host-io` rows for `run_status` to
    `tests/data/seat_launch_references.json` and change no other row.
  - verify: Run V0 and V3. For each SL-0 control in artifact §13, use the
    ENVELOPE in-process mutation pattern: assert the fragment is present
    exactly once, exec the mutated module, then the production witness passes
    and the mutated witness fails. Record the per-control outcomes.

### SL-1 — Replay projection, liveness, bounded pages and reader view

- **Scope**: Derive replaceable projections, liveness-checked attempt status, bounded pages and separated reader views from SL-0 reads only.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`, `phase-loop-runtime/tests/test_run_status_projection.py`
- **Interfaces provided**: `project_assignment`, `check_projection`, `attempt_status`, `read_page`, `check_page`, `build_reader_view`, `check_reader_view`, `proc_observer`, `SL-1 results` (signatures in artifact §10)
- **Interfaces consumed**: `read_index`, `read_attempt`, `resolve_run`, `process_start_identity`, `make_ref`, `_run_status_vectors`, `validate_record` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Run every projection, liveness, reader_view and page vector through
    the production entries in artifact §12 with exact diagnostic sets and
    display effects. Add local cases:
    - Ordering: admission order defeats contradictory lexical attempt-id
      order, contradictory mtimes and `observed_at` values.
    - Latest attempt: an unknown latest attempt never falls back to an
      earlier one.
    - Projections: a cached stale or ahead projection reports `stale` or is
      refused, never `current`.
    - Liveness: a real subprocess writer that is killed reports
      `stale_unknown`, and a recorded start identity that differs from the
      live process (pid reuse) does too.
    - Pages: page-size bounds of 0, 1, 100, 101 and null; the 20-attempt
      span; `omitted` and `has_more` always present; resolver-reported
      `retention_dropped` counts; `evidence_unknown`; cursor
      tamper/foreign/out-of-range refusals; and continuation after further
      appends.
    - Reader views: closed `runtime_state` phrases, refusal of `run_status` as
      an outcome or evidence source, and a foreign row join.
    - Secrecy: sentinel bytes written through SL-0 never appear in
      projections, statuses, pages or views. `termination`, `refusal` and
      `result_binding` pass through `attempt_status` unchanged.
  - impl: Implement artifact §8 as replay-only code with no cache, file write,
    listener or watch. Build `proc_observer` on `process_start_identity`, and
    perform no direct filesystem primitive in this module: the unchanged
    inventory row set enforces that. Every produced projection, page and view
    passes `validate_record` and its semantic checker before it is returned.
  - verify: Run V1 and V3. Run the SL-1 mutation controls in artifact §13 the
    same way as SL-0, and record the per-control outcomes.

### SL-2 — Documentation, evidence and receipt reducer

- **Scope**: Synthesize both producer lanes into the canonical run-status documentation, a metadata-only receipt and a receipt test.
- **Owned files**: `docs/supervised-run-status.md`, `plans/evidence/supervised-worker/JOURNAL.md`, `phase-loop-runtime/tests/test_run_status_receipt.py`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `plans/manifest.json`
- **Interfaces provided**: `plans/evidence/supervised-worker/JOURNAL.md` (runner-stamped per-node outcomes, mutation witnesses, source/artifact bindings and the deferred-obligation list)
- **Interfaces consumed**: `SL-0 results`, `SL-1 results`, `reserve_attempt`, `read_attempt`, `project_assignment`
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_run_status_receipt.py` follows the ENVELOPE receipt pattern.
    It checks the receipt's file digests against the tree and the frozen
    artifact digest against the manifest seal. It calls the production API for
    one positive reservation/terminal/projection round trip and for one
    `journal_torn_line` read. It fails on missing results, stale bindings,
    skipped-only nodes or a fixture claimed authoritative. Text snapshots are
    never the oracle.
  - impl: Write `docs/supervised-run-status.md`:
    - the API, storage layout, trust checks, reservation ordering and crash
      windows, the diagnostic map, display rules, caps and closed phrases;
    - the unsupported same-login forgery boundary, the absence of journal
      pruning (outside `output_retention` roots), fail-closed index recovery,
      and that run status is never a work outcome.
    Record in the receipt every deferred pinned obligation for CLOSEOUT and
    the consumer obligations from artifact §11. Add one Unreleased CHANGELOG
    entry (internal API, no CLI) and a `docs_updated` decision in
    `.doc-decisions.json`. Do a manual catalog audit and change
    `.claude/docs-catalog.json` only if it lists supervised docs. Append
    lifecycle metadata to this plan's manifest entry without touching
    `frozen_inputs`.
  - verify: Run V2, then the effective suite. In a temporary copy, falsify one
    receipt binding after the production calls and assert rejection. Record
    only observed results, never a predicted pass.

## Execution Notes

- **Lane order**: lanes are sequential with disjoint, complete ownership.
  SL-2 is the only reducer and depends on both producers. No subagent,
  scheduler fanout or worktree creation is authorized.
- **Single-writer files**: `tests/data/seat_launch_references.json` belongs to
  SL-0. SL-1 adds no filesystem primitive, so it needs no row.
  `test_seat_reference_inventory.py` stays unchanged.
- **Untouched files**: `supervised_launch*.py`, `supervised_contracts.py`, the
  vendored schemas, `convergence/**`, `output_retention.py`, `cli.py`,
  `pyproject.toml`, `uv.lock` and all `__init__.py` files stay untouched. New
  modules are auto-discovered.
- **Destructive changes**: none. Every lane is purely additive, apart from
  appending rows to the inventory, the CHANGELOG, the decisions file and the
  manifest.
- **Release**: this phase neither tags nor dispatches a release, so no
  post-dispatch lane is needed.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated
  worktrees do not see sibling-lane merges automatically. If a lane finds its
  worktree base is pre-SL-0's merge, it MUST stop and report rather than
  committing — the orchestrator will re-spawn or rebase. Silent
  `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces
  commits that destroy peer-lane work on `--no-ff` merge.
- **Deferred to CLOSEOUT**: the authoritative v2-intake rerun of all 35
  vectors, the v2 `kind=echo` reconciliation and any renamed public code.
  Readiness requires CLOSEOUT's live checks, Gate A and board review; this
  plan dispatches none of them.
- **Consumer mismatches**, recorded rather than silently absorbed:
  - LANEEXEC `x-status-cancel` names only queued/running/cancelling plus
    terminal. `attempt_status` can also return `unknown` and `stale_unknown`,
    so LANEEXEC must map them.
  - The PLACECLI `OpaqueId` allows 256 characters, but the public run-status
    caps `run_id`/`attempt_id` at 128, so LANEEXEC ids must fit.
  - CLOSEOUT's "six echo cases through the real JOURNAL writer" conflicts with
    EC-JOURNAL-4's digest-only rule. The index digest is the proposed anchor
    (artifact §11).
  - PLACECLI itself makes no journal assumption beyond "landed and
    reconciled". Its reservation journal is a separate store.
- **Next phase**: JOURNAL is execution-ready for manual, separately authorized
  execution. Next command: `claude-execute-phase plans/phase-plan-v12-JOURNAL.md`
  under that authority. WORKER's plan consumes IF-0-JOURNAL-1 as frozen here.

## Open Questions

1. The roadmap scope notes say "Decompose into 2 lanes". This plan adds the
   skill-mandated terminal documentation/evidence reducer as SL-2, which owns
   no runtime code. If the owner reads "2 lanes" as a hard cap, fold SL-2 into
   SL-1 by amendment.
2. A crash mid-append can leave a torn index tail, which makes that assignment
   `index_unverifiable` until an operator intervenes, because the roadmap
   forbids torn-tail repair. Should a sealed, explicitly disclosed recovery
   record be allowed in a later phase?
3. The journal root defaults to `$XDG_STATE_HOME`, an environment-derived
   location. Should WORKER and LANEEXEC instead require an operator-configured
   root (the API already accepts one)?
4. `process_start_time` uses a Linux `/proc` identity, so other platforms
   refuse writer open. Is a Linux-only supervised worker acceptable for v12?
5. The initial event phrase set is a proposal for WORKER. Additions need a
   plan amendment, which the WORKER planner should confirm.

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-0: effort=high, reason=crash-window ordering and cross-process reservation durability
- SL-2: effort=low, reason=documentation and receipt reducer

## Acceptance Criteria

- [ ] EC-JOURNAL-1 — proven by V0 (storage trust, writer lock, fsync spy,
  rotation and journal vectors), falsified by path-entered `component_nofollow`,
  `owner_check`, `mode_check`, `index_fsync` and `segment_chain` mutants
  reaching production `open_journal_root`/`AttemptWriter`.
- [ ] EC-JOURNAL-2 — proven by V0 journal-vector exact sets plus the
  missing/unindexed/read-only cases, falsified by `torn_line`,
  `unknown_version`, `foreign_writer`, `seq_gap`, `identity_key` and
  `reader_readonly` mutants in production `read_attempt`.
- [ ] EC-JOURNAL-3 — proven by V0 subprocess reservation races and the crash
  kill, plus V1 ordering, projection, liveness and pid-reuse cases,
  falsified by `attempt_excl`, `index_lock`, `index_order`, `latest_fallback`,
  `projection_behind`, `owner_live` and `pid_reuse` mutants at production
  `reserve_attempt`/`project_assignment`/`attempt_status`.
- [ ] EC-JOURNAL-4 — proven by V1 page, reader-view and sentinel cases and the
  V0 secrecy scan, falsified by `page_bound`, `omitted_counts`,
  `retention_count`, `runtime_phrase_set`, `outcome_source` and
  `ref_digest_only` mutants in production `read_page`/`build_reader_view`/`make_ref`.

## Verification

Owner shared-host rule: run each command serially under `timeout 900` with
`-p no:cacheprovider`. The locked environment has no pytest-xdist, so pytest is
already serial and `-n 0` would be a usage error; never add `-n`. Check `uptime` and `/proc/pressure/io` before each
command and stop if the host is degraded. Use the locked Python 3.12+
environment and the absolute source/test PYTHONPATH from CONTRIBUTING.md, and
assert `phase_loop_runtime.__file__` resolves inside the checkout under test.
Full suites, Gate A and CI stay hosted.

Before implementation, pytest `--collect-only` must find zero nodes for V0–V2.
Afterwards, every node V0–V2 select must lie in a lane-owned file, each owned
test file must contribute nodes, and the receipt records the node IDs. Zero
collection, skipped-only results or exit 5 fail verification. All tests run
offline.

- V0: `python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_run_status.py`
- V1: `python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_run_status_projection.py`
- V2: `python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_run_status_receipt.py`
- V3: `python3 -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_seat_reference_inventory.py`
- Effective suite: the frontmatter `automation.suite_command`.

Validate argv and the effective suite through IF-0-VC-2
(`verification_evidence.validate_verification_commands`) at execution intake,
once the V0–V2 files exist. Report multiple failures, and flag any single node
that costs more than about five minutes.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-run-status.md`
- evidence paths: `plans/evidence/supervised-worker/JOURNAL.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing or malformed evidence routes to `blocker_class=contract_bug`,
`human_required=false`.
