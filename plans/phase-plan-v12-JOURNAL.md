---
phase_loop_plan_version: 1
phase: JOURNAL
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5
automation:
  suite_command: ["timeout", "900", "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", "phase-loop-runtime/tests/test_run_status.py", "phase-loop-runtime/tests/test_run_status_projection.py", "phase-loop-runtime/tests/test_run_status_receipt.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
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

Revision 2 applies the 2026-11-08 advisor-board verdict on agent-harness#1925
(APPROVE-WITH-EDITS) and the owner rulings below.

**Key input finding.** The run-status family needs no synthetic labels. The
SCHEMA phase vendored `run-status.schema.json` and
`conformance/run-status.vectors.json`. Their bytes are identical at the v1 pin,
at the CLOSEOUT v2 pin and at the v13 `x-contract-pins.run_status` pin
(`plans/artifacts/v12-JOURNAL-interface.md` §1). JOURNAL therefore implements
against the pinned vocabulary and rules, and runs all 35 run-status vectors
through production paths as early reconciliation evidence. CLOSEOUT still
discharges authoritative acceptance (roadmap Execution Notes). The publisher
status is `provisional`.

Existing code inspected:

- `convergence/event_log.py` provides the durability discipline to reuse:
  dir_fd/O_NOFOLLOW opens, `flock`, full writes and file/directory `fsync`.
  Its torn-tail `ftruncate` repair must **not** be reused.
- `convergence/status.py` is the replay-only projection pattern to reuse.
- `output_retention._directory`/`_locked` show uid/mode and lock checks.
- `rfc8785` is already a runtime dependency.
- `supervised_launch.consume_admission` keeps its single-use token only
  in-process. JOURNAL supplies the durable cross-process reservation.
- The landed `test_supervised_contracts_receipt.py::test_runtime_consumers_remain_independent`
  forbids runtime modules from importing or naming `supervised_contracts`. So
  production validates with the stdlib plus `rfc8785`, and only tests call
  `validate_record` (artifact §1).

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
  The exact signatures, storage layout, admission-index format, reservation and
  fsync ordering, diagnostic map, caps, cursor and closed phrase sets are in
  `plans/artifacts/v12-JOURNAL-interface.md` §2–§10. Evidence:
  `plans/evidence/supervised-worker/JOURNAL.md`.

These are harness-local Python APIs. Public records are exactly the pinned
run-status definitions. The admission index, local codes, cursor and caps are
harness-local and never enter a public record. Artifact §2–§8 carry the
mechanisms for EC-JOURNAL-1, EC-JOURNAL-2, EC-JOURNAL-3 and EC-JOURNAL-4, plus
the reservation EC-WORKER-2 consumes. This plan does not restate those criteria.

The board fixed four interface points:

- `reserve_attempt` mints `writer_instance_id` and returns it in
  `Reservation.writer`, and `open_writer` copies it unchanged.
- Production modules never import or name `supervised_contracts`.
- The §4 writer-format rules and the §9 phrase rules bind `AttemptWriter` and
  display output only, never readers.
- `PageResult` carries `next_cursor`.

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
- **Interfaces consumed**: `rfc8785` (pre-existing); tests only: `load_contract_bundle` (pre-existing), `validate_record` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Build `_run_status_vectors.py` per artifact §12. In
    `test_run_status.py`, run every `kind=journal` vector through
    `read_index`/`read_attempt` with exact diagnostic sets and display effects.
    The controls carry foreign-format writer strings and non-§9 messages, and
    must read clean. Add local cases:
    - Structural checker: run a differential against `validate_record` on
      every vector and produced record, and assert its tables equal the
      pinned schema's.
    - Storage trust: wrong owner, group/world modes, symlinked components,
      hardlinked segments, non-regular entries, unexpected entries, a root
      inside an `excluded` root, and invalid or over-128-character ids.
      `default_journal_root()` ignores a hostile `HOME` and `XDG_STATE_HOME`.
    - Reader integrity: missing journal, missing segment and unindexed attempt
      (display `unknown`), plus identity-versus-directory/index mismatch.
    - Writer rules: every lifecycle violation, a non-phrase event, the line cap
      with terminal headroom across rotation, and rotation chaining.
    - Writer poisoning: inject a failure into `os.write` or `os.fsync`. Every
      later append refuses `writer_poisoned` and the bytes stay unchanged.
    - Writer identity: the index entry, every journal line and
      `Reservation.writer` carry one `writer_instance_id`.
    - Writer ownership: refusal of a second writer, a resumed writer and a
      writer in a different process. Reader runs leave every byte, mode and
      mtime unchanged.
    - Reservation: refuses duplicate, terminal, cross-assignment and
      crash-reserved ids, and refuses on a torn or broken index. Run real
      `sys.executable -I` subprocess races where N processes reserve one
      attempt id: exactly one wins. Kill a reserving child after the
      directory claim and before the index append, then show the id can
      never be reused and reads as `attempt_unindexed`. An empty run record
      refuses `run_record_unreadable`. `resolve_run` of an absent run returns
      `()`.
    - Durability: an `os.fsync` spy proves the complete §5 fsync order,
      including the `assignments/` parent and the run claim, before
      `reserve_attempt` returns.
    - Secrecy: plant prompt, source, secret and argv sentinels in bytes passed
      to `make_ref`, then scan every byte under the root to show they are
      absent and only digests appear. Tests pin umask 077 and set unsafe modes
      explicitly with `chmod`.
  - impl: Implement artifact §1–§7 and §9 without importing or naming
    `supervised_contracts`. Reuse the event_log durability pattern without its
    truncation. Map I/O and parse exceptions to closed codes `from None`;
    diagnostics carry no values or paths. Add exact `host-io` rows for
    `run_status` to `tests/data/seat_launch_references.json` and change no other
    row.
  - verify: Run V0, V3 and V4. For each SL-0 control in artifact §13, use the
    ENVELOPE in-process mutation pattern: assert the fragment is present
    exactly once, exec the mutated module, then the production witness passes
    and the mutated witness fails. Record the per-control outcomes.

### SL-1 — Replay projection, liveness, bounded pages and reader view

- **Scope**: Derive replaceable projections, liveness-checked attempt status, bounded pages and separated reader views from SL-0 reads only.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`, `phase-loop-runtime/tests/test_run_status_projection.py`
- **Interfaces provided**: `project_assignment`, `check_projection`, `attempt_status`, `read_page`, `check_page`, `build_reader_view`, `check_reader_view`, `proc_observer`, `SL-1 results` (signatures in artifact §10)
- **Interfaces consumed**: `read_index`, `read_attempt`, `resolve_run`, `process_start_identity`, `make_ref`, `_run_status_vectors`; tests only: `validate_record` (pre-existing)
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
    - Pages: page-size bounds of 0, 1, 100, 101 and null, and the 20-attempt
      span. Header lines are never events and are counted in `omitted`.
      `has_more` is always present, and `next_cursor` is present exactly when
      `has_more` is true; continuation works after further appends.
      Resolver-reported `retention_dropped` counts go through
      `evidence(identity, ref)`, an `unknown` result gives `evidence_unknown`,
      and cursor tamper, foreign and out-of-range values are refused.
    - Reader views: closed `runtime_state` phrases, refusal of `run_status` as
      an outcome or evidence source, and a foreign row join.
    - Secrecy: sentinel bytes written through SL-0 never appear in
      projections, statuses, pages or views. `termination`, `refusal` and
      `result_binding` pass through `attempt_status` unchanged.
  - impl: Implement artifact §8 as replay-only code with no cache, file write,
    listener or watch, and without importing or naming `supervised_contracts`.
    Build `proc_observer` on `process_start_identity`, and perform no direct
    filesystem primitive: the unchanged inventory row set enforces that. Every
    produced projection, page and view passes the structural checker and its
    semantic checker before it is returned.
  - verify: Run V1, V3 and V4. Run the SL-1 mutation controls in artifact §13
    the same way as SL-0, and record the per-control outcomes.

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
    - the API, the fixed per-user root, storage layout, trust checks,
      reservation and fsync ordering, crash windows, the diagnostic map,
      display rules, caps and closed phrases;
    - the Linux-only requirement and the unsupported same-login forgery
      boundary;
    - that a deleted final segment cannot be detected;
    - the manual operator quarantine procedure, and the absence of journal
      pruning (outside `output_retention` roots);
    - that run status is never a work outcome.
    Record in the receipt every deferred pinned obligation for CLOSEOUT and
    the artifact §11 obligations. Add one Unreleased CHANGELOG entry (internal
    API, no CLI) and a `docs_updated` decision in `.doc-decisions.json`. Do a
    manual catalog audit and change `.claude/docs-catalog.json` only if it
    lists supervised docs. Append lifecycle metadata to this plan's manifest
    entry without touching `frozen_inputs`.
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
- **Untouched files**: `supervised_launch*.py`, `supervised_contracts.py` and
  its tests, the vendored schemas, `convergence/**`, `output_retention.py`,
  `cli.py`, `pyproject.toml`, `uv.lock` and all `__init__.py` files stay
  untouched. New modules are auto-discovered.
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
  vectors, the `kind=echo` reconciliation and any renamed public code.
  Readiness requires CLOSEOUT's live checks, Gate A and board review; this
  plan dispatches none of them.
- **Downstream amendments**: the board named amendments for WORKER,
  LANEEXEC, PLACECLI and CLOSEOUT. They are listed in artifact §11 and the PR
  body, and are not made here.
- **Next phase**: JOURNAL is execution-ready for manual, separately authorized
  execution. Next command: `claude-execute-phase plans/phase-plan-v12-JOURNAL.md`
  under that authority. WORKER's plan consumes IF-0-JOURNAL-1 as frozen here.

## Owner Rulings

Recorded 2026-11-08 from the board's recommended answers, which the owner
accepted as routine plan choices:

1. **Lane count**: three lanes are accepted. SL-2 is the skill-mandated
   reducer and owns no runtime code.
2. **Torn admission index**: manual operator quarantine is enough in v12. The
   operator renames the directory aside and keeps its bytes, and its ids stay
   claimed. The sealed recovery record is deferred (artifact §5).
3. **Journal root**: one fixed per-user root, derived from `pw_dir`, ignoring
   the environment (artifact §2).
4. **Platform**: a Linux-only supervised worker is acceptable for v12 and is
   documented.
5. **Event phrases**: the eight phrases are confirmed, plus one general
   `proposal withheld` (artifact §9).
6. **Runtime validation**: production code has no `supervised_contracts`
   import. It uses the stdlib plus `rfc8785`, and `validate_record` stays in
   tests.

No open questions remain for this phase.

## Execution Policy

- execute: effort=medium, reason=contract-bound implementation against a frozen artifact
- SL-0: effort=high, reason=crash-window ordering and cross-process reservation durability
- SL-2: effort=low, reason=documentation and receipt reducer

## Acceptance Criteria

- [ ] EC-JOURNAL-1 — proven by V0 (storage trust, writer lock, fsync order spy,
  poisoning, rotation and journal vectors), falsified by path-entered `component_nofollow`,
  `owner_check`, `mode_check`, `index_fsync`, `assignment_dir_fsync`,
  `run_claim_fsync`, `writer_poison` and `segment_chain` mutants reaching
  production `open_journal_root`/`reserve_attempt`/`AttemptWriter`.
- [ ] EC-JOURNAL-2 — proven by V0 journal-vector exact sets plus the
  missing/unindexed/read-only cases, falsified by `torn_line`,
  `unknown_version`, `foreign_writer`, `writer_instance_reuse`, `seq_gap`,
  `identity_key` and `reader_readonly` mutants in production `read_attempt`/`open_writer`.
- [ ] EC-JOURNAL-3 — proven by V0 subprocess reservation races and the crash
  kill, plus V1 ordering, projection, liveness and pid-reuse cases,
  falsified by `attempt_excl`, `index_lock`, `index_order`, `latest_fallback`,
  `projection_behind`, `owner_live` and `pid_reuse` mutants at production
  `reserve_attempt`/`project_assignment`/`attempt_status`.
- [ ] EC-JOURNAL-4 — proven by V1 page, reader-view and sentinel cases and the
  V0 secrecy scan, falsified by `page_bound`, `header_not_event`, `omitted_counts`,
  `retention_count`, `next_cursor`, `runtime_phrase_set`, `outcome_source` and
  `ref_digest_only` mutants in production `read_page`/`build_reader_view`/`make_ref`.

## Verification

Shared-host rule: before each command, check load average against `nproc`,
`free -h` available memory (defer below about 6 GiB), `/proc/pressure/io`,
`/proc/pressure/memory` and the effective cgroup memory and CPU limits. Stop or
defer if any of them is degraded. Run serially under `timeout 900` with
`-p no:cacheprovider`, and never add `-n`: the locked environment has no
pytest-xdist. V0–V4 run the locked environment through `uv run --locked` with
the CONTRIBUTING.md groups and absolute source/test PYTHONPATH, and assert
`phase_loop_runtime.__file__` resolves inside the checkout under test. A literal
`.venv/bin/python` path is avoided because uv's interpreter symlink resolves
outside the repository, which IF-0-VC-2 rejects (`outside_repo_path`). The
frontmatter suite calls `python3`, which the runner's interpreter shim resolves
to its locked interpreter. Full suites, Gate A and CI stay hosted.

Before implementation, pytest `--collect-only` must find zero nodes for V0–V2.
Afterwards, every node V0–V2 select must lie in a lane-owned file, each owned
test file must contribute nodes, and the receipt records the node IDs. Zero
collection, skipped-only results or exit 5 fail verification. All tests run
offline.

- V0: `PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" timeout 900 uv run --project phase-loop-runtime --locked --group test --extra visual python -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_run_status.py`
- V1: `PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" timeout 900 uv run --project phase-loop-runtime --locked --group test --extra visual python -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_run_status_projection.py`
- V2: `PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" timeout 900 uv run --project phase-loop-runtime --locked --group test --extra visual python -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_run_status_receipt.py`
- V3: `PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" timeout 900 uv run --project phase-loop-runtime --locked --group test --extra visual python -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_seat_reference_inventory.py`
- V4: `PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" timeout 900 uv run --project phase-loop-runtime --locked --group test --extra visual python -m pytest -q -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_receipt.py -k test_runtime_consumers_remain_independent`
- Effective suite: the frontmatter `automation.suite_command`, which names the
  four phase test files.

Validate argv and the effective suite through IF-0-VC-2
(`verification_evidence.validate_verification_commands`) at execution intake,
once the V0–V2 files exist. Until then it reports `missing_path` for exactly
those three files; V3, V4 and every other argument already validate. Report multiple failures, and flag any single
node that costs more than about five minutes.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-run-status.md`
- evidence paths: `plans/evidence/supervised-worker/JOURNAL.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing or malformed evidence routes to `blocker_class=contract_bug`,
`human_required=false`.
