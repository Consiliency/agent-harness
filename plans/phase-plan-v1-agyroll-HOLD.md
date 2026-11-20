---
phase_loop_plan_version: 1
phase: HOLD
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 2e14646a3468513b00e8dff197769395a7b0f4882c27ae882b2dff6c4cdee1ed
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_agy_hold_cache.py tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_doctor.py tests/test_agy_integrity_seat_admission.py tests/test_agy_static_integrity.py tests/test_agy_catalog_data.py tests/test_advisor_board_config.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_self_qualification.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# HOLD: Availability floor

## Context

HOLD lets a Gemini seat run an already-qualified agy image when its selected one cannot be
used for a subject-side reason. The design is frozen in
`plans/artifacts/agyfresh-contract.md` (AGYFRESH §2, §4, §6), pinned in the roadmap's
External Inputs. This plan does not restate it. Files, the staged admission order, test
cases, run lists and stop rules are in `plans/artifacts/agyfresh-hold-lanes.md` (**lanes
artifact**, §A–§G).

**Lanes.** The roadmap's four lanes map as follows:

- Feasibility (F0): done, and it failed (roadmap Assumption 5). Its probe test ships in SL-1.
- Core → SL-1. Cache → SL-2.
- Dotfiles: Consiliency/dotfiles, under EXT-DOT; not a lane here.
- SL-3 is the REQUAL early slice (FAILEXP). It is scheduled here because it is the next
  writer of `agy_qualification.py` after the cache lane; its goals are REQUAL's and its
  plan is `plans/detailed-agyfresh-failexp-20261120-0114.md`.

**Base.** SL-1 builds on RESTORE's caps lane (IF-0-RESTORE-1). Two handoffs from that
lane's review bind SL-1: `agy_qualification.lookup` keeps ownership of the sealed image it
is given, and a memfd seal failure is never a hold reason, including after
`agy_integrity.check` has mapped it to `AgyImageUnqualified`.

**Binding inputs.**

- Owner decisions D3a, D3b, D3c, D4, D5 (roadmap "Owner Decisions").
- Coordinator ruling R-F0-1: SL-1 and SL-2 skip managed-release subjects (no search, no
  cache); status and doctor show "not covered (managed release)"; SL-1 amends AGYFRESH §2.6.
- Coordinator ruling R-F0-2: SL-1 enumerates the non-jailed heartbeat route and applies the
  managed skip or justifies coverage.
- AGYFRESH §6.2 and §6.3, which tell this plan to record the option it chose.

**Options chosen** (lanes artifact §B):

- **Selection promise (§6.2).** The full ordered walk runs on every hold. The only process
  memo records rejected files, still spends the read budget, and never admits or reorders
  (§B1).
- **Replacement detection (§6.3): option (b).** After the read, a descriptor-relative
  no-follow stat of the candidate's name must match the opened inode; a mismatch or a
  missing name rejects. Limit: a swap reverted before that stat is not seen, and is
  harmless because only sealed bytes whose digest passes AGYFRESH §2.3 run. Option (a) is
  neither built nor tested (§B2).
- **Managed skip.** One predicate in `admit_seat`, by subject, using the resolver's
  managed-root test read-only (§B3).
- **A held admission carries no path** (§B4). The jailed standalone route executes by path,
  so it refuses a held admission as it refuses today. Covering that route is open question
  Q1; it is not built here.
- **Reader and writer split.** SL-1 reads `held/`; SL-2 writes it (§B5).

**Invariants.** No new refusal code (AGYFRESH §4). No store key, catalog, record or pin
change. No edit to `panel_invoker.py`, `seat_jail.py`, `seat_subject.py` or anything on the
AGYFRESH §3 list. `admission_verdict(execute=False)` is unchanged.

## Interface Freeze Gates

- [ ] IF-0-HOLD-1 — AGYFRESH §2.1–§2.7 with §6.2–§6.3 as resolved in lanes artifact §B1–§B4:
  - `agy_qualification.admit_seat` (AGYFRESH §2.2 signature), `_SubjectNotAdmitted`, `admit_held`;
  - `agy_qualification.hold_status(env, subject_path)` returning the object of §B6;
  - `agy_hold` constants and `HeldCandidate` (AGYFRESH §2.4), `hold_enabled()`, `hold_deny()`;
  - `gemini_heartbeat.catalog_members(path=None) -> list[dict]`;
  - `[agy] hold` and `[agy] hold_deny` (user config);
  - evidence keys `provider_admission_source`, `provider_hold_reason`, `provider_subject_image_sha256`.
- [ ] IF-0-HOLD-2 — AGYFRESH §2.8: `agy_hold.retain(image, store)`, pruning to `HELD_KEEP`, `clear --all` removing `held/`, with the gates of lanes artifact §B7.
- [ ] IF-0-HOLD-4 — the recorded outcome: managed-release subjects are not covered; the route table of lanes artifact §C; `coverage: "not_covered_managed_release"`.
- IF-0-HOLD-3 (Consiliency/dotfiles `stage_agy`) is produced under EXT-DOT, not by a lane here.

## Lane Index & Dependencies

SL-1 — HOLD-CORE: admission boundary, hold, discovery, status
  Depends on: (none)
  Blocks: SL-2, SL-3, SL-4
  Parallel-safe: no

SL-2 — HOLD-CACHE: retain, prune, clear
  Depends on: SL-1
  Blocks: SL-3, SL-4
  Parallel-safe: no

SL-3 — FAILEXP: failed-entry expiry and the doctor row
  Depends on: SL-1, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-4 — Documentation & spec reconciliation
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

The chain is strictly sequential: one PR per lane, each merged before the next starts.
`Owned files` names each file once, under the first lane that writes it. A later lane's
`Continues` line lists the files it also edits after the owner has merged; no two lanes are
ever open on one file.

## Lanes

### SL-1 — HOLD-CORE: admission boundary, hold, discovery, status
- **Scope**: Route every seat admission through `admit_seat`, hold on typed subject-side failures only, find candidates by a bounded, ordered, descriptor-relative search, skip managed subjects, and report the hold in evidence and status.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_hold.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/advisor-boards.example.toml`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_agy_hold.py`, `phase-loop-runtime/tests/test_agy_hold_managed.py`, `phase-loop-runtime/tests/test_agy_catalog_data.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/test_agy_integrity_seat_admission.py`, `phase-loop-runtime/tests/test_agy_static_integrity.py`, `phase-loop-runtime/tests/test_seats_teamhost_gemini.py`, `phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `plans/artifacts/agyfresh-contract.md`, `specs/phase-plans-agyroll-v1.md`, `plans/phase-plan-v1-agyroll-HOLD.md`
- **Interfaces provided**: IF-0-HOLD-1, IF-0-HOLD-4, `admit_seat`, `admit_held`, `hold_status`, `agy_hold.retain` (no-op), `catalog_members`
- **Interfaces consumed**: IF-0-RESTORE-1 (pre-existing), `seat_subject._names_managed_root` (pre-existing), `tests/test_agy_hold_managed.py` from the feasibility lane (pre-existing)
- **Parallel-safe**: no
- **Notes**:
  - Files and per-file changes: lanes artifact §D1. Stage order of `admit_seat` and the
    candidate loop's error rule: §D2. Test matrix: §D3. Run list and stop rules: §D4.
  - First task: re-check the route table (§C) by grep. A missing or wrong row stops the lane.
  - The feasibility tests are added byte-identical; new managed and jailed-standalone cases
    are appended to that file.
  - Contract amendment in this PR (R-F0-1): AGYFRESH §2.6 and §2.9, plus the sentences §B1,
    §B2 and §B4 replace. Then the roadmap's External Inputs row is repinned to the committed
    file and this plan's frontmatter digest is re-stamped. Nothing else in the roadmap changes.
  - Test names carry `ec_hold_<n>`, so each goal has a selector.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | (none) | `tests/test_agy_hold_managed.py` | the eight feasibility tests, unmodified | `pytest tests/test_agy_hold_managed.py` |
| SL-1.2 | test | SL-1.1 | `tests/test_agy_hold.py`, `tests/test_agy_hold_managed.py`, `tests/test_agy_catalog_data.py`, `tests/test_advisor_board_config.py`, `tests/conftest.py` | lanes artifact §D3 | `pytest tests/test_agy_hold.py -k ec_hold` |
| SL-1.3 | impl | SL-1.2 | `agy_hold.py`, `gemini_heartbeat.py`, `advisor_board/config.py`, example config | (none) | `pytest tests/test_agy_hold.py -k "ec_hold_7 or ec_hold_9"` |
| SL-1.4 | impl | SL-1.3 | `agy_qualification.py`, `agy_integrity.py`, moved-hook test files, inventory | (none) | `pytest tests/test_agy_hold.py tests/test_agy_hold_managed.py` |
| SL-1.5 | docs | SL-1.4 | `CONTRACTS.md`, capabilities card, `CHANGELOG.md`, AGYFRESH contract, roadmap row, this plan's frontmatter | (none) | `python phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-agyroll-HOLD.md` |
| SL-1.6 | verify | SL-1.5 | lanes artifact §D4 run list | all | §D4 |

### SL-2 — HOLD-CACHE: retain, prune, clear
- **Scope**: Keep the last two admitted images in a digest-addressed, lock-coordinated cache under the store, and remove them on `clear --all`.
- **Owned files**: `phase-loop-runtime/tests/test_agy_hold_cache.py`
- **Continues**: SL-1's `agy_hold.py`, `agy_qualification.py`, `tests/data/seat_launch_references.json`, `CONTRACTS.md`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-HOLD-2
- **Interfaces consumed**: IF-0-HOLD-1, `agy_hold.retain` (no-op), `admit_seat`
- **Parallel-safe**: no
- **Notes**: Files, tests, run list and stop rules: lanes artifact §E. All mutations take `Store.lock()` and use `dir_fd` (AGYFRESH §2.5); `retain` never waits and never raises. Gates: §B7. The selection promise binds this lane too: the §B1 mirror test.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | (none) | `tests/test_agy_hold_cache.py` | lanes artifact §E | `pytest tests/test_agy_hold_cache.py` |
| SL-2.2 | impl | SL-2.1 | `agy_hold.py`, `agy_qualification.py`, inventory | (none) | `pytest tests/test_agy_hold_cache.py -k ec_hold_10` |
| SL-2.3 | docs | SL-2.2 | `CONTRACTS.md`, `CHANGELOG.md` | (none) | (none) |
| SL-2.4 | verify | SL-2.3 | lanes artifact §E run list | all | §E |

### SL-3 — FAILEXP: failed-entry expiry and the doctor row
- **Scope**: Expire repeated-transient failed entries and name an active or not-covered hold in the doctor's Gemini row (the REQUAL early slice).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/doctor.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.golden.json`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`, `docs/TEAM-ONBOARDING.md`
- **Continues**: SL-1's `agy_qualification.py`, `tests/test_agy_self_qualification.py`, `tests/test_agy_hold.py`, `CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`
- **Interfaces provided**: the failed-class part of IF-0-REQUAL-1 (pre-existing gate, REQUAL)
- **Interfaces consumed**: `hold_status`, IF-0-HOLD-1, IF-0-HOLD-2
- **Parallel-safe**: no
- **Notes**: Changes, verification and acceptance: `plans/detailed-agyfresh-failexp-20261120-0114.md`. Its goals belong to REQUAL and are accepted there, not in this plan's Acceptance Criteria.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | (none) | `tests/test_agy_self_qualification.py`, `tests/test_agy_hold.py`, `tests/test_seats_teamhost_doctor.py` | detailed plan, Changes | `pytest tests/test_seats_teamhost_doctor.py -k hold` |
| SL-3.2 | impl | SL-3.1 | `agy_qualification.py`, `doctor.py`, doctor schema and golden | (none) | `pytest tests/test_agy_self_qualification.py -k "expir or legacy or violation"` |
| SL-3.3 | docs | SL-3.2 | `CONTRACTS.md`, card, `TEAM-ONBOARDING.md`, `CHANGELOG.md` | (none) | (none) |
| SL-3.4 | verify | SL-3.3 | detailed plan, Verification | all | detailed plan |

### SL-4 — Documentation & spec reconciliation
- **Scope**: After the three PRs, confirm the docs each lane carried agree with what landed, record the spec closeout, and update the plan manifest lifecycle; no code change.
- **Owned files**: `plans/manifest.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-HOLD-1, IF-0-HOLD-2, IF-0-HOLD-4, `hold_status`
- **Parallel-safe**: no
- **Notes**: Each code lane writes its own `CONTRACTS.md`, card and `CHANGELOG.md` text, because hosted CI checks docs per PR. This reducer only checks them against the merged code and the lanes artifact's open questions, and records which were ruled. The reducer itself is `no_doc_delta`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | (none) | (none) | (none) | the frontmatter `suite_command` |
| SL-4.2 | docs | SL-4.1 | `plans/manifest.json` | (none) | `python phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-agyroll-HOLD.md` |

## Verification

Per lane: the run lists in lanes artifact §D4 and §E and in the detailed plan. Whole phase:
the frontmatter `suite_command`, which is:

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_agy_hold_cache.py \
  tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_doctor.py \
  tests/test_agy_integrity_seat_admission.py tests/test_agy_static_integrity.py \
  tests/test_agy_catalog_data.py tests/test_advisor_board_config.py \
  tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_size_bounds.py \
  tests/test_agy_qci.py tests/test_seat_reference_inventory.py
PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_self_qualification.py
timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract
phase-loop agy-qualification status   # read-only; expect a "hold" object
```

Shared-host rule: these files only, serially, under `timeout`, after a headroom check. The
locked venv has no xdist, so `-n 0` is passed only where it is installed; never `-n auto`.
Hosted CI before each merge: the full pytest job, the `agy catalog contract` job, and,
because `agy_*.py` and `gemini_heartbeat.py` change, the strict conformance run and
`--release` check from the roadmap's Verification section; Gate A where docs change. No
live provider call is part of this phase.

## Execution Notes

- **Execution.** One implementer and one PR per lane, in order. The lane IR cannot express
  two sequential lanes on one file, which is why later lanes use `Continues`; do not run
  these lanes as a parallel wave.
- **Single-writer files.** `agy_qualification.py` and `agy_hold.py`: SL-1 → SL-2 (→ SL-3
  for the first). `gemini_heartbeat.py` and `agy_integrity.py`: SL-1 only; EXECADMIT is the
  next phase to write them. Append-only shared files (`CONTRACTS.md`, `CHANGELOG.md`,
  `tests/data/seat_launch_references.json`): each lane adds its own section or rows.
- **Requalification.** None intended. `tests/test_agy_qci.py` decides, under AGYFRESH §3.
- **Not covered, stated in the docs each lane writes.** Managed-release subjects
  (EC-HOLD-6, second branch) and the jailed standalone route (lanes artifact §B4, Q1).
- **Open questions** for the coordinator: lanes artifact §G (Q1–Q5). None blocks SL-1.
  A ruling on Q1 or Q2 that changes scope is a plan amendment before SL-1 opens its PR, or
  a follow-up lane after it.
- **Stop rule.** If any authority, projection or jail check would have to change for a
  test to pass, the lane stops and reports.
- **Rollback.** `[agy] hold = false` per host; every lane reverts with no state migration;
  `clear --all` frees the cache.
- **Known destructive changes**: none.
- **Release.** This phase dispatches no release; `CHANGELOG.md` entries go under `[Unreleased]`.
- **Effort.** SL-1 and SL-3: high. SL-2: medium. SL-4: low.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`.

- [ ] EC-HOLD-1 — proven by `pytest tests/test_agy_hold.py -k ec_hold_1`; falsified by the same cases with no candidate present (the original refusal must return) and by a subject-side reason that admits without `provider_admission_source == "lkg"`. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-2 — proven by `pytest tests/test_agy_hold.py -k ec_hold_2`; falsified by the candidate-opener spy recording a call, or by a seal failure reaching the hold handler. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-3 — proven by `pytest tests/test_agy_hold.py -k ec_hold_3`; falsified by `_run_help` being called for a candidate with no provenance entry. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-4 — proven by `pytest tests/test_agy_hold.py -k ec_hold_4`; falsified by a `qualify` stub that is never called. Path-entered control: through `admit_seat(first_use=True)` with the production first-use body.
- [ ] EC-HOLD-5 — proven by `pytest tests/test_agy_hold.py -k ec_hold_5`; falsified by `admission_verdict(execute=False)` returning `admits` for a non-member. Path-entered control: through `admission_verdict` and `agy_integrity.admit_for_seat` with the user config file on disk.
- [ ] EC-HOLD-6 — second branch (not covered), proven by `pytest tests/test_agy_hold_managed.py`; falsified by removing the digest gate in `_prepare_jailed_gemini` (the feasibility cases fail) or by a managed subject opening a candidate. Path-entered control: through `panel_invoker._prepare_jailed_gemini` and the real projection and jail admission.
- [ ] EC-HOLD-7 — proven by `pytest tests/test_agy_hold.py -k ec_hold_7`; falsified by an older cache image beating a newer vendor member, or by a memo making an earlier admitted image beat a newer eligible one. Path-entered control: through `admit_seat` over a vendor store and `held/` built on disk; the opener is not stubbed.
- [ ] EC-HOLD-8 — proven by `pytest tests/test_agy_hold.py -k ec_hold_8`; falsified by two images open at once. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-9 — proven by `pytest tests/test_agy_hold.py -k ec_hold_9`; falsified by deleting the final name stat (the rename case is then admitted) or by a symlinked candidate being read. Path-entered control: through `admit_seat` over files on disk, with the swap injected at the production `os.open` and read sites.
- [ ] EC-HOLD-10 — proven by `pytest tests/test_agy_hold_cache.py -k ec_hold_10`; falsified by a partial file after concurrent retain and clear. Path-entered control: through `admit_seat(first_use=True)` and `cli_main` `clear --all` on a real store directory.
- [ ] EC-HOLD-11 — proven in Consiliency/dotfiles by `pytest tests/test_seat_authority.py` under EXT-DOT; falsified by `Refused` while a retained image verifies. No lane here changes it. Path-entered control: through that repository's `stage_agy`.
- [ ] EC-HOLD-12 — proven by `pytest tests/test_agy_hold.py -k ec_hold_12`; falsified by a `status` output with no `hold` key, or one that names a held image for a managed subject. Path-entered control: through `cli_main` `status`.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `plans/artifacts/agyfresh-contract.md`, `specs/phase-plans-agyroll-v1.md`
- evidence paths: `phase-loop-runtime/tests/test_agy_hold.py`, `phase-loop-runtime/tests/test_agy_hold_cache.py`, `phase-loop-runtime/tests/test_agy_hold_managed.py`
- redaction posture: `metadata_only`
- downstream handling: roadmap amendment limited to the External Inputs repin of the AGYFRESH contract (SL-1); REQUAL's remaining lanes are planned on the roadmap after PROVFWD
