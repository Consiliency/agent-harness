---
phase_loop_plan_version: 1
phase: HOLD
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 2e14646a3468513b00e8dff197769395a7b0f4882c27ae882b2dff6c4cdee1ed
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_agy_hold_jail.py tests/test_agy_hold_cache.py tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_doctor.py tests/test_seat_jail.py tests/test_gemini_seat_egress_1170.py tests/test_agy_integrity_seat_admission.py tests/test_agy_static_integrity.py tests/test_agy_catalog_data.py tests/test_advisor_board_config.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_self_qualification.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# HOLD: Availability floor

## Context

HOLD lets a Gemini seat run an already-qualified agy image when its selected one cannot be
used for a subject-side reason. Revision 3 of this plan follows two reviews, one owner
decision and the coordinator's rulings on the second review.

**Inputs this plan points at and does not restate:**

- `plans/artifacts/agyfresh-contract.md` (AGYFRESH), pinned in the roadmap's External
  Inputs: the design.
- `plans/artifacts/agyfresh-hold-amendment.md` (**amendment**): the exact text lane SL-0
  lands in the roadmap and in AGYFRESH.
- `plans/artifacts/agyfresh-hold-lanes.md` (**lanes artifact**, §A–§J): files, stage order,
  test cases, run lists and stop rules per lane.
- `plans/detailed-agyfresh-failexp-20261120-0114.md`: lane SL-5.

**Owner decision (2026-11-20), jailed standalone seat: "Do it: sandbox runs verified
copy."** The jailed standalone route executes the provider by path, so a held admission
could not run there, and on a host that can jail, the Gemini review seat takes only that
route. The route now binds the admitted sealed image. This needs the roadmap's seat-jail
non-goal and HOLD's stop rule amended explicitly (SL-0), a feasibility gate before any jail
code (SL-1), and its own integration lane (SL-3). The managed projection and its digest
gate stay as they are; managed hosts recover at build time.

**Coordinator rulings on the second review, as applied here:**

1. **One mount form, no fallback.** The proc-descriptor bind keeps every canonical jail
   digest and qualification key. A data bind would change the one canonical Gemini digest,
   which the managed route's canonical gate, the dependency-branch normalization, the
   qualification key and the qualifier's own jail all share; it cannot be frozen without
   touching the managed branch, so it is **ruled out** (amendment §2.8). If SL-1 shows the
   proc-descriptor form fails any check, SL-3 does not start and the owner decides between
   a new amendment and accepting the gap.
2. **SL-1 selects on every check**, run through the real owner launch chain and uid drop,
   on one local host; other configurations by static or recorded evidence only; never `ai`.
3. **Release hold G-REL** is an execution gate of this plan (below).
4. **SL-3's assertions** include the surviving descriptor set, credential and owner-store
   sentinels, and the digest of the bytes actually executed.

**Other binding inputs.** Owner decisions D3a, D3b, D3c, D4, D5. Coordinator rulings
R-F0-1 (skip managed-release subjects; "not covered (managed release)") and R-F0-2
(enumerate the non-jailed heartbeat route). AGYFRESH §6.2 and §6.3. The seven handoffs
H1–H7 from the RESTORE caps lane's review (lanes artifact §I).

**Options this plan records** (lanes artifact §B; landed as contract text by SL-0):

- **Selection promise (§6.2): no process memo.** The full ordered walk runs on every hold.
- **Replacement detection (§6.3): option (b).** After the read, a descriptor-relative
  no-follow stat of the candidate's name must match the opened inode. It detects an
  observed replacement, not every one; the sealed digest is the integrity control. Option
  (a) is neither built nor tested.
- **Managed skip:** one predicate in `admit_seat`, by subject.
- **A held admission carries no path.** Routes execute the sealed image only.
- **Status is route-aware and reports a candidate, never use** (review R2).

**Invariants.** No new refusal code. No store key, catalog, record or pin change. No edit
to `seat_subject.py` or anything on the AGYFRESH §3 list. The only jail change is the
standalone Gemini provider bind. `admission_verdict(execute=False)` is unchanged.

## Interface Freeze Gates

- [ ] IF-0-HOLD-1 — AGYFRESH §2.1–§2.7 as amended:
  - `agy_qualification.admit_seat`, `_SubjectNotAdmitted`, `admit_held`;
  - `agy_qualification.hold_status(env, subject_path)` returning the amended §2.6 object;
  - `agy_hold` constants and `HeldCandidate`, `hold_enabled()`, `hold_deny()`, `ROUTE_COVERAGE`;
  - `gemini_heartbeat.catalog_members(path=None) -> list[dict]`;
  - `[agy] hold` and `[agy] hold_deny` (user config);
  - evidence keys `provider_admission_source`, `provider_hold_reason`, `provider_subject_image_sha256`.
- [ ] IF-0-HOLD-2 — AGYFRESH §2.8 as amended: `agy_hold.retain(image, store)`, pruning to `HELD_KEEP`, `clear --all` removing `held/`.
- [ ] IF-0-HOLD-4 — the recorded F0 outcome: managed-release subjects are not covered on any route.
- [ ] IF-0-HOLD-5 — amendment §2.8 (AGYFRESH §2.11): `seat_jail.build_seat_jail(..., provider_fd=)`, the proc-descriptor bind, which launches use it, descriptor ownership, and the jailed seat's evidence keys. Declared by SL-0's roadmap amendment.
- IF-0-HOLD-3 (Consiliency/dotfiles `stage_agy`) is produced under EXT-DOT, not by a lane here.

## Lane Index & Dependencies

SL-0 — AMEND: roadmap and contract amendment
  Depends on: (none)
  Blocks: SL-2, SL-3, SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-1 — JAILPROBE: sealed-image jail feasibility gate
  Depends on: (none)
  Blocks: SL-3, SL-6
  Parallel-safe: yes

SL-2 — HOLD-CORE: admission boundary, hold, discovery, status
  Depends on: SL-0
  Blocks: SL-3, SL-4, SL-5, SL-6
  Parallel-safe: no

SL-3 — JAILBIND: the standalone Gemini jail binds the sealed image
  Depends on: SL-0, SL-1, SL-2
  Blocks: SL-4, SL-5, SL-6
  Parallel-safe: no

SL-4 — HOLD-CACHE: retain, prune, clear
  Depends on: SL-2, SL-3
  Blocks: SL-5, SL-6
  Parallel-safe: no

SL-5 — FAILEXP: failed-entry expiry and the doctor row
  Depends on: SL-2, SL-3, SL-4
  Blocks: SL-6
  Parallel-safe: no

SL-6 — Documentation & spec reconciliation
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5
  Blocks: (none)
  Parallel-safe: no

External prerequisite for every lane: RESTORE's caps lane and its contract repin are merged
(IF-0-RESTORE-1). SL-0 and SL-1 run in parallel; they share no file. SL-2 to SL-5 are
strictly sequential, one PR each, each merged before the next starts. `Owned files` names
each file once, under the first lane that writes it; a later lane's `Continues` line lists
the files it also edits after the owner has merged.

**Execution gate G-REL (release hold).** Release owner: the Agent-Harness Exec, who
records the hold in the engagement plan and ledger. No tag, PyPI publication or deployment
may contain SL-3 until its exemption is proven by SL-1's recorded digest comparison and by
EC-HOLD-14 passing in hosted CI on SL-3's final head. A publication reaches the dotfiles
nightly consumers by itself, so the hold is on the tag; if any deployment consumes `main`
directly, SL-3's merge waits too. A change that moved a canonical key is outside this plan
(SL-3 stops); under a later amendment it would stay held until owner step O4 covered every
affected host (amendment §1.4).

## Lanes

### SL-0 — AMEND: roadmap and contract amendment
- **Scope**: Land the amendment text in the roadmap and in AGYFRESH in one docs PR, repin the roadmap's External Inputs row, and re-stamp this plan's frontmatter digest.
- **Owned files**: `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyfresh-contract.md`, `plans/phase-plan-v1-agyroll-HOLD.md`
- **Interfaces provided**: EC-HOLD-13, EC-HOLD-14, EC-HOLD-15, the amended EC-HOLD-9 and EC-REQUAL-8, IF-0-HOLD-5 (declaration), release hold G-REL, AGYFRESH §2.11
- **Interfaces consumed**: IF-0-RESTORE-1 (pre-existing), the amendment artifact (pre-existing)
- **Parallel-safe**: yes
- **Notes**: Text: the amendment, verbatim, and nothing else. Baseline: both files after the caps lane's repin (H6). Uses `phase-roadmap-builder` in amendment mode. Hosted: Gate A, because docs change.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | (none) | roadmap, contract | (none) | `python -m phase_loop_runtime.roadmap_lint specs/phase-plans-agyroll-v1.md` |
| SL-0.2 | docs | SL-0.1 | roadmap, contract, this plan's frontmatter | (none) | `python phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-agyroll-HOLD.md` |
| SL-0.3 | verify | SL-0.2 | the three files | (none) | `git diff --check` and both commands above |

### SL-1 — JAILPROBE: sealed-image jail feasibility gate
- **Scope**: Decide, by observed runs on one local host with a stand-in executable and no production change, whether the proc-descriptor bind of the sealed image works in the standalone Gemini jail and which launches may use it.
- **Owned files**: `phase-loop-runtime/tests/test_agy_hold_jail.py`, `plans/evidence/agyfresh-jailbind-feasibility.md`
- **Interfaces provided**: the feasibility result (go with a launch scope, or stop) for IF-0-HOLD-5
- **Interfaces consumed**: IF-0-RESTORE-1 (pre-existing), `seat_jail._owner_argv` (pre-existing), `seat_jail.jail_profile_digest` (pre-existing)
- **Parallel-safe**: yes
- **Notes**: Checks P1–P7, all required, and the decision rule: lanes artifact §D. Every check runs through the real owner launch chain and the uid drop, with the conformance stand-in; no agy, network, credential or provider call. One local host, after a headroom check; other supported configurations by static or recorded evidence only; a second-host run is a separate request to the coordinator; never `ai`. Any failing check stops the jail work. Whether a memfd can be a bind source is not assumed. The probe file merges with SL-3.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | (none) | `tests/test_agy_hold_jail.py` | probe cases P1–P7 | `pytest tests/test_agy_hold_jail.py -k probe` |
| SL-1.2 | docs | SL-1.1 | `plans/evidence/agyfresh-jailbind-feasibility.md` | (none) | (none) |

### SL-2 — HOLD-CORE: admission boundary, hold, discovery, status
- **Scope**: Route every seat admission through `admit_seat`, hold on typed subject-side failures only, find candidates by a bounded, ordered, descriptor-relative search, skip managed subjects, and report the hold in evidence and in a route-aware status.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_hold.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_integrity.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/advisor-boards.example.toml`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_agy_hold.py`, `phase-loop-runtime/tests/test_agy_hold_managed.py`, `phase-loop-runtime/tests/test_agy_catalog_data.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/test_agy_integrity_seat_admission.py`, `phase-loop-runtime/tests/test_agy_static_integrity.py`, `phase-loop-runtime/tests/test_seats_teamhost_gemini.py`, `phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py`, `phase-loop-runtime/tests/test_agy_size_bounds.py`, `phase-loop-runtime/tests/test_agy_qci.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-HOLD-1, IF-0-HOLD-4, `admit_seat`, `admit_held`, `hold_status`, `agy_hold.ROUTE_COVERAGE`, `agy_hold.retain` (no-op), `catalog_members`
- **Interfaces consumed**: IF-0-RESTORE-1 (pre-existing), `seat_subject._names_managed_root` (pre-existing), `tests/test_agy_hold_managed.py` from the F0 lane (pre-existing), AGYFRESH §2.11
- **Parallel-safe**: no
- **Notes**:
  - Files: lanes artifact §E1. Stage order and the H1–H4 rules: §E2. Tests: §E3. Run list and stop rules: §E4.
  - First task: re-check the route table (§C) by grep. A missing or wrong row stops the lane.
  - The F0 tests are added byte-identical; new cases are appended to that file.
  - The jailed standalone route still refuses a held admission in this lane, and status says `not_covered` for it.
  - This lane edits neither the roadmap nor the contract.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | (none) | `tests/test_agy_hold_managed.py` | the eight F0 tests, unmodified | `pytest tests/test_agy_hold_managed.py` |
| SL-2.2 | test | SL-2.1 | `tests/test_agy_hold.py`, `tests/test_agy_hold_managed.py`, `tests/test_agy_catalog_data.py`, `tests/test_advisor_board_config.py`, `tests/conftest.py` | lanes artifact §E3 | `pytest tests/test_agy_hold.py -k ec_hold` |
| SL-2.3 | impl | SL-2.2 | `agy_hold.py`, `gemini_heartbeat.py`, `advisor_board/config.py`, example config | (none) | `pytest tests/test_agy_hold.py -k "ec_hold_7 or ec_hold_9"` |
| SL-2.4 | impl | SL-2.3 | `agy_qualification.py`, `agy_integrity.py`, moved-hook test files, inventory | (none) | `pytest tests/test_agy_hold.py tests/test_agy_hold_managed.py` |
| SL-2.5 | docs | SL-2.4 | `CONTRACTS.md`, capabilities card, `CHANGELOG.md` | (none) | (none) |
| SL-2.6 | verify | SL-2.5 | lanes artifact §E4 run list | all | §E4 |

### SL-3 — JAILBIND: the standalone Gemini jail binds the sealed image
- **Scope**: Make the jailed standalone Gemini route execute the admitted sealed image in both its production and probe jails, with the three evidence keys, by the proc-descriptor bind, changing no canonical digest and leaving the managed branch and the qualifier untouched.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_gemini_seat_egress_1170.py`, `phase-loop-runtime/tests/test_seats_teamhost_integration.py`, `phase-loop-runtime/tests/test_seat_qualification_key.py`
- **Continues**: SL-1's `tests/test_agy_hold_jail.py`; SL-2's `agy_hold.py` (`ROUTE_COVERAGE`), `tests/test_agy_hold.py`, `tests/test_agy_hold_managed.py`, `tests/test_agy_qci.py`, `tests/data/seat_launch_references.json`, `CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-HOLD-5
- **Interfaces consumed**: the feasibility result (SL-1), `admit_seat`, `agy_hold.ROUTE_COVERAGE`, AGYFRESH §2.11
- **Parallel-safe**: no
- **Notes**:
  - Files, and the modules that are not edited: lanes artifact §F1. Tests: §F2. Cost, release hold and stop rules: §F3.
  - Starts only if every SL-1 check passed. The launch scope (held only, or every standalone launch) is the one SL-1's report recommends.
  - "What ran" is measured by the stand-in hashing its own running image, not by reading the path.
  - Proves, unstubbed, that the managed-dependency jail and the jail the qualifier builds still pass the canonical comparison; it edits neither.
  - Under G-REL: the PR's first paragraph states the hold and links both proofs.
  - Cases that launch bwrap must run in hosted CI; a run that skips them all is not a pass.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | (none) | `tests/test_agy_hold_jail.py`, `tests/test_agy_hold_managed.py`, `tests/test_agy_hold.py` | lanes artifact §F2 | `pytest tests/test_agy_hold_jail.py -k "ec_hold_13 or ec_hold_14"` |
| SL-3.2 | impl | SL-3.1 | `seat_jail.py` | (none) | `pytest tests/test_agy_hold_jail.py tests/test_seat_jail.py` |
| SL-3.3 | impl | SL-3.2 | `panel_invoker.py`, `agy_hold.py`, moved-stub test files, inventory | (none) | `pytest tests/test_agy_hold_jail.py tests/test_agy_hold_managed.py tests/test_gemini_seat_egress_1170.py` |
| SL-3.4 | docs | SL-3.3 | `CONTRACTS.md`, card, `CHANGELOG.md` | (none) | (none) |
| SL-3.5 | verify | SL-3.4 | lanes artifact §F3 run list | all | §F3 |

### SL-4 — HOLD-CACHE: retain, prune, clear
- **Scope**: Keep the last two admitted images in a digest-addressed, lock-coordinated cache under the store, and remove them on `clear --all`.
- **Owned files**: `phase-loop-runtime/tests/test_agy_hold_cache.py`
- **Continues**: SL-2's `agy_hold.py`, `agy_qualification.py`, `tests/data/seat_launch_references.json`, `CONTRACTS.md`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-HOLD-2
- **Interfaces consumed**: IF-0-HOLD-1, IF-0-HOLD-5, `agy_hold.retain` (no-op), `admit_seat`
- **Parallel-safe**: no
- **Notes**: Files, tests, run list and stop rules: lanes artifact §G. All mutations take `Store.lock()` and use `dir_fd`; `retain` never waits and never raises. Cache files stay 0600 and are never bound into a jail.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-4.1 | test | (none) | `tests/test_agy_hold_cache.py` | lanes artifact §G | `pytest tests/test_agy_hold_cache.py` |
| SL-4.2 | impl | SL-4.1 | `agy_hold.py`, `agy_qualification.py`, inventory | (none) | `pytest tests/test_agy_hold_cache.py -k ec_hold_10` |
| SL-4.3 | docs | SL-4.2 | `CONTRACTS.md`, `CHANGELOG.md` | (none) | (none) |
| SL-4.4 | verify | SL-4.3 | lanes artifact §G run list | all | §G |

### SL-5 — FAILEXP: failed-entry expiry and the doctor row
- **Scope**: Expire repeated-transient failed entries and show the hold candidate, its state and the route coverage in the doctor's Gemini row (the REQUAL early slice).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/doctor.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.schema.json`, `phase-loop-runtime/src/phase_loop_runtime/schemas/phase-loop-doctor.v1.golden.json`, `phase-loop-runtime/tests/test_seats_teamhost_doctor.py`, `docs/TEAM-ONBOARDING.md`
- **Continues**: SL-2's `agy_qualification.py`, `tests/test_agy_self_qualification.py`, `tests/test_agy_hold.py`, `CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`
- **Interfaces provided**: the failed-class part of IF-0-REQUAL-1 (pre-existing gate, REQUAL)
- **Interfaces consumed**: `hold_status`, IF-0-HOLD-1, IF-0-HOLD-2, IF-0-HOLD-5
- **Parallel-safe**: no
- **Notes**: Changes, verification and acceptance: the detailed plan. Its goals belong to REQUAL and are accepted there.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | (none) | `tests/test_agy_self_qualification.py`, `tests/test_agy_hold.py`, `tests/test_seats_teamhost_doctor.py` | detailed plan, Changes | `pytest tests/test_seats_teamhost_doctor.py -k hold` |
| SL-5.2 | impl | SL-5.1 | `agy_qualification.py`, `doctor.py`, doctor schema and golden | (none) | `pytest tests/test_agy_self_qualification.py -k "expir or legacy or violation"` |
| SL-5.3 | docs | SL-5.2 | `CONTRACTS.md`, card, `TEAM-ONBOARDING.md`, `CHANGELOG.md` | (none) | (none) |
| SL-5.4 | verify | SL-5.3 | detailed plan, Verification | all | detailed plan |

### SL-6 — Documentation & spec reconciliation
- **Scope**: After the lanes, confirm the docs each lane carried agree with what landed, record the spec closeout and SL-1's result against EC-HOLD-14, and update the plan manifest lifecycle; no code change.
- **Owned files**: `plans/manifest.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-HOLD-1, IF-0-HOLD-2, IF-0-HOLD-4, IF-0-HOLD-5, `hold_status`
- **Parallel-safe**: no
- **Notes**: Each code lane writes its own `CONTRACTS.md`, card and `CHANGELOG.md` text, because hosted CI checks docs per PR. The reducer itself is `no_doc_delta`. It records whether G-REL's two proofs exist; without them the phase is not complete.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | (none) | (none) | (none) | the frontmatter `suite_command` |
| SL-6.2 | docs | SL-6.1 | `plans/manifest.json` | (none) | `python phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-agyroll-HOLD.md` |

## Verification

Per lane: the run lists in lanes artifact §E4, §F3 and §G and in the detailed plan. Whole
phase: the frontmatter `suite_command`, then, read-only,
`phase-loop agy-qualification status` (expect a `hold` object with `routes`).

Shared-host rule: the listed files only, serially without `-n`, under `timeout`, after a
headroom check; never a full suite. Hosted CI before each merge: the full pytest job, the
`agy catalog contract` job, and, because `agy_*.py`, `gemini_heartbeat.py` and
`panel_invoker.py` change, the strict conformance run and `--release` check from the
roadmap's Verification section; Gate A where docs or package data change. No live provider
call and no jail qualification run on a host is part of any lane.

## Execution Notes

- **Execution.** One implementer and one PR per lane. The lane IR cannot express two
  sequential lanes on one file, which is why later lanes use `Continues`; only SL-0 and
  SL-1 may be open together.
- **Single-writer files.** `agy_qualification.py`: SL-2 → SL-4 → SL-5. `agy_hold.py`:
  SL-2 → SL-3 (one constant) → SL-4. `panel_invoker.py` and `seat_jail.py`: SL-3 only in
  this phase. Append-only shared files (`CONTRACTS.md`, `CHANGELOG.md`,
  `tests/data/seat_launch_references.json`): each lane adds its own section or rows and
  keeps the caps lane's `_open_image_fd` row (H6).
- **Handoff H7** is not this phase's work: PROVFWD and ROLLJOB keep `_ExpandedReader` and
  `_bounded_tarinfo`, and ROLLJOB owes streaming for `fetch_member(keep_bytes=True)`. It is
  passed to those phases' plans.
- **Requalification.** agy: none intended; `tests/test_agy_qci.py` decides under AGYFRESH
  §3. Jail: none, because no canonical digest or key changes; EC-HOLD-14 proves it and
  G-REL holds the release until it has. The analysis is amendment §2.8–§2.9.
- **Cost of the jail work.** Two extra lanes (SL-1 small, SL-3 medium to high) and two
  files this phase did not touch before. No extra memory.
- **Not covered, stated in the docs each lane writes.** Managed-release subjects, on every
  route (EC-HOLD-6, second branch). The jailed standalone route until SL-3 merges.
- **Open questions**: lanes artifact §J. None blocks a lane.
- **Stop rule.** As amended (amendment §1.4): the managed projection, its digest gate, the
  authority path, or any jail property other than the §2.11 bind.
- **Rollback.** `[agy] hold = false` per host; every lane reverts with no state migration;
  `clear --all` frees the cache. Reverting SL-3 changes no canonical key.
- **Known destructive changes**: none.
- **Release.** This phase dispatches no release; `CHANGELOG.md` entries go under
  `[Unreleased]`.
- **Effort.** SL-2, SL-3 and SL-5: high. SL-1 and SL-4: medium. SL-0 and SL-6: low.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`. EC-HOLD-13 to -15 are declared by SL-0's
roadmap amendment; until it lands, the validator reports them as not yet in the roadmap.

- [ ] EC-HOLD-1 — proven by `pytest tests/test_agy_hold.py -k ec_hold_1`; falsified by the same cases with no candidate present (the original refusal must return) and by a subject-side reason that admits without `provider_admission_source == "lkg"`. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-2 — proven by `pytest tests/test_agy_hold.py -k ec_hold_2`; falsified by the candidate-opener spy recording a call, or by a seal failure or an unavailable seal ABI reaching the hold handler. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-3 — proven by `pytest tests/test_agy_hold.py -k ec_hold_3`; falsified by `_run_help` being called for a candidate with no provenance entry. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-4 — proven by `pytest tests/test_agy_hold.py -k ec_hold_4`; falsified by a `qualify` stub that is never called. Path-entered control: through `admit_seat(first_use=True)` with the production first-use body.
- [ ] EC-HOLD-5 — proven by `pytest tests/test_agy_hold.py -k ec_hold_5`; falsified by `admission_verdict(execute=False)` returning `admits` for a non-member. Path-entered control: through `admission_verdict` and `agy_integrity.admit_for_seat` with the user config file on disk.
- [ ] EC-HOLD-6 — second branch (not covered), proven by `pytest tests/test_agy_hold_managed.py`; falsified by removing the digest gate in `_prepare_jailed_gemini` (the F0 cases fail) or by a managed subject opening a candidate. Path-entered control: through `panel_invoker._prepare_jailed_gemini` and the real projection and jail admission.
- [ ] EC-HOLD-7 — proven by `pytest tests/test_agy_hold.py -k ec_hold_7`; falsified by an older cache image beating a newer vendor member, or by an earlier admitted image beating a newer eligible one. Path-entered control: through `admit_seat` over a vendor store and `held/` built on disk; the opener is not stubbed.
- [ ] EC-HOLD-8 — proven by `pytest tests/test_agy_hold.py -k ec_hold_8`; falsified by two images open at once, or by a hold whose traced peak exceeds `OVERHEAD_CEILING`. Path-entered control: through `admit_seat(first_use=True)` and `agy_integrity.admit_for_seat`.
- [ ] EC-HOLD-9 — proven by `pytest tests/test_agy_hold.py -k ec_hold_9`; falsified by deleting the final name stat (the rename case is then admitted) or by a symlinked candidate being read. Path-entered control: through `admit_seat` over files on disk, with the swap injected at the production `os.open` and read sites.
- [ ] EC-HOLD-10 — proven by `pytest tests/test_agy_hold_cache.py -k ec_hold_10`; falsified by a partial file after concurrent retain and clear. Path-entered control: through `admit_seat(first_use=True)` and `cli_main` `clear --all` on a real store directory.
- [ ] EC-HOLD-11 — proven in Consiliency/dotfiles by `pytest tests/test_seat_authority.py` under EXT-DOT; falsified by `Refused` while a retained image verifies. No lane here changes it. Path-entered control: through that repository's `stage_agy`.
- [ ] EC-HOLD-12 — proven by `pytest tests/test_agy_hold.py -k ec_hold_12`; falsified by a `status` output with no `hold` key. Path-entered control: through `cli_main` `status`.
- [ ] EC-HOLD-13 — proven by `pytest tests/test_agy_hold_jail.py -k ec_hold_13` in hosted CI with the bwrap cases executed; falsified by restoring the path bind for a held admission (the source-rewrite case then executes other bytes), by an unsealed descriptor being accepted, by a descriptor outside the declared set surviving in the provider, or by a descriptor left open after a failed build. Path-entered control: through `panel_invoker._prepare_jailed_gemini`, the real `seat_jail.build_seat_jail` and the production owner chain, with the executed stand-in reporting its own digest.
- [ ] EC-HOLD-14 — proven by `pytest tests/test_agy_hold_jail.py -k ec_hold_14` in hosted CI on SL-3's final head, with `plans/evidence/agyfresh-jailbind-feasibility.md`; falsified by any leg's canonical digest or the launch key differing from its base value, or by the managed-dependency jail or the qualifier's jail failing the real `_require_canonical_jail`. These two proofs are what releases G-REL. Path-entered control: through `seat_jail.build_seat_jail`, `seat_jail_qualification._launch_probe` and `panel_invoker._require_canonical_jail`, none stubbed.
- [ ] EC-HOLD-15 — proven by `pytest tests/test_agy_hold.py -k ec_hold_15`; falsified by a status that names a candidate for a managed subject, reports the jailed route covered before SL-3, or calls a candidate in use. Path-entered control: through `cli_main` `status`.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyfresh-contract.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `phase-loop-runtime/tests/test_agy_hold.py`, `phase-loop-runtime/tests/test_agy_hold_cache.py`, `phase-loop-runtime/tests/test_agy_hold_managed.py`, `phase-loop-runtime/tests/test_agy_hold_jail.py`, `plans/evidence/agyfresh-jailbind-feasibility.md`
- redaction posture: `metadata_only`
- downstream handling: roadmap amendment (SL-0, text in `plans/artifacts/agyfresh-hold-amendment.md`); release hold G-REL on SL-3; REQUAL's remaining lanes are planned on the amended roadmap after PROVFWD
