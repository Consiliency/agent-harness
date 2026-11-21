---
phase_loop_plan_version: 1
phase: HOLD
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 6c48caeb931380e5da226760f65b2c7790a44ee3a311595dee6f7cff12f190df
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_hold.py tests/test_agy_hold_managed.py tests/test_agy_hold_jail.py tests/test_agy_hold_cache.py tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_doctor.py tests/test_seat_jail.py tests/test_gemini_seat_egress_1170.py tests/test_agy_integrity_seat_admission.py tests/test_agy_static_integrity.py tests/test_agy_catalog_data.py tests/test_advisor_board_config.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_self_qualification.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# HOLD: Availability floor

## Context

HOLD lets a Gemini seat run an already-qualified agy image when its selected one cannot be
used for a subject-side reason. Revision 5 of this plan follows four reviews, one owner
decision and the coordinator's rulings on the reviews.

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
route. The first design, binding the admitted sealed image, failed its feasibility lane
(SL-1): neither bubblewrap nor the kernel binds a memfd. The owner asked for a new design.
For a held admission the route now runs a private per-launch copy of the admitted image,
held under a checked name and bound by the existing path bind
(`plans/artifacts/agyfresh-jailbind-v2.md`). The managed projection and its digest gate
stay as they are; managed hosts recover at build time.

**Rulings that still apply:**

1. **Held only.** Ordinary jailed launches keep the existing path bind, with launch and
   evidence behaviour preserved apart from one additive evidence key.
2. **No jail property changes**, and `seat_jail.py` is not edited, so no canonical jail
   digest or qualification key can change. A data bind stays ruled out.
3. **The guarantee rests on custody of the staged copy.** Where AGYFRESH §2.11 provides
   a runtime check it is a fail-closed backstop; where it does not, the route has no
   runtime check of the executing image. Either way the execution window is an accepted,
   recorded risk.
4. **Release hold G-REL: the control is the merge** (Lane Index, below).
5. **Feasibility first.** SL-7 decides whether the staged-copy design works, on one local
   host, through the real owner launch chain and uid drop; never `ai`.

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
- **A held admission carries no path.** The memfd routes execute the sealed image; the
  jailed route executes a private copy staged from it.
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
- [ ] IF-0-HOLD-5 — The standalone Gemini jail's staged private copy for a held admission, its checked name, its start gate, and its evidence (AGYFRESH §2.11). Produced by SL-3.
- IF-0-HOLD-3 (Consiliency/dotfiles `stage_agy`) is produced under EXT-DOT, not by a lane here.

## Lane Index & Dependencies

Branch recorded at the SL-1 checkpoint: STOP, new amendment; amended by
`plans/amendments/agyroll-HOLD-jailbind-v2.md`.

SL-0 — AMEND: roadmap and contract amendment
  Depends on: (none)
  Blocks: SL-2, SL-4, SL-5, SL-6
  Parallel-safe: yes

SL-1 — JAILPROBE: sealed-image jail feasibility gate
  Depends on: (none)
  Blocks: SL-6
  Parallel-safe: yes

SL-2 — HOLD-CORE: admission boundary, hold, discovery, status
  Depends on: SL-0
  Blocks: SL-3, SL-4, SL-5, SL-6
  Parallel-safe: no

SL-4 — HOLD-CACHE: retain, prune, clear
  Depends on: SL-2
  Blocks: SL-5, SL-6
  Parallel-safe: no

SL-5 — FAILEXP: failed-entry expiry and the doctor row
  Depends on: SL-2, SL-4
  Blocks: SL-3, SL-6
  Parallel-safe: no

SL-7 — JAILPROBE2: staged-copy feasibility gate
  Depends on: (none)
  Blocks: SL-8, SL-3, SL-6
  Parallel-safe: yes

SL-8 — AMEND2: roadmap, contract and HOLD plan amendment
  Depends on: SL-7
  Blocks: SL-3, SL-6
  Parallel-safe: no

SL-3 — JAILBIND v2: a held admission's standalone Gemini jail runs a staged private copy
  Depends on: SL-2, SL-5, SL-7, SL-8
  Blocks: SL-6
  Parallel-safe: no

SL-6 — Documentation & spec reconciliation
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4, SL-5, SL-7, SL-8
  Blocks: (none)
  Parallel-safe: no

External prerequisite for every lane: RESTORE's caps lane and its contract repin are merged
(IF-0-RESTORE-1). SL-0 and SL-1 run in parallel; they share no file. After them, one PR per
lane, each merged before the next starts. `Owned files` names each file once, under the
first lane that writes it; a later lane's `Continues` line lists the files it also edits
after the owner has merged.

**History.** SL-1 reported STOP on the first jail design, and the branch checkpoint
recorded "STOP, new amendment". The jail lane and the reducer were then restored by the
amendment `plans/amendments/agyroll-HOLD-jailbind-v2.md`. The branch table and checkpoint
procedure of lanes artifact §A and §K are spent and no longer direct execution.

**Order.** SL-2 → SL-4 → SL-5 as before. SL-7 (feasibility) may run beside them; SL-8
(docs) follows the coordinator's GO on SL-7's report; SL-3 follows SL-5 and SL-8; SL-6
closes the phase. If SL-7 ends in STOP, SL-8, SL-3 and SL-6 do not run, and lanes artifact
§K2's edits apply if the owner accepts the gap.

**Execution gate G-REL (release hold): the control is the merge.** Release owner and
**only merge actor** for SL-3: the Agent-Harness Exec.

- **Clearance.** Recorded by the release owner in the engagement plan and ledger. It names
  the cleared head SHA and links (i) SL-7's report on `main`, with its digest comparison;
  (ii) that head's hosted CI run showing both hosted groups **executed with zero skips**,
  the EC-HOLD-14 cases and the EC-HOLD-13 cases that need no jail, and the cases that need
  a real jail as well where SL-7's report showed the runner can launch one; and (iii)
  SL-3's recorded dev0 run of the cases that need a real jail.
- **Merge.** Only by a head-conditioned merge on the cleared SHA
  (`gh pr merge --match-head-commit <cleared-sha>`, or the train runner's equivalent
  head-conditioned merge), after every required check has passed on that same head. If the
  PR head differs at merge time the clearance is invalid, and the head condition makes the
  merge fail rather than race a push.
- **No unattended path.** SL-3 is excluded from auto-merge and from any queued or deferred
  merge. The standing approval to merge accepted PRs does not replace the clearance.
- `main` therefore stays releasable at every tag, and a deployment that consumes `main`
  directly is covered by the same gate; no pre-tag check is needed.

**SL-7 outcome (recorded): GO, observed.** SL-7's report on `main`,
`plans/evidence/agyfresh-jailbind-v2-feasibility.md`, recommends GO with the runtime check
observed, and the coordinator ruled that its check V5 holds. SL-8 therefore lands the
"observed" text of the v2 contract; its custody-only variant (§4.5) is not landed. The
decision and the report's notes for SL-3 are recorded in AGYFRESH §2.11.

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
- **Scope**: Decide, by observed runs on one local host with a stand-in executable and no production change, whether the proc-descriptor bind of the sealed image works in the standalone Gemini jail: GO or STOP.
- **Owned files**: `plans/evidence/agyfresh-jailbind-feasibility.md`
- **Interfaces provided**: the feasibility result (GO or STOP) for IF-0-HOLD-5
- **Interfaces consumed**: IF-0-RESTORE-1 (pre-existing), `seat_jail._owner_argv` (pre-existing), `seat_jail.jail_profile_digest` (pre-existing)
- **Parallel-safe**: yes
- **Notes**: **Completed; historical.** This lane ran and reported STOP on the first design; its text is kept as the record of that probe and directs no further work. Checks P1–P7, all required, and the decision rule: lanes artifact §D. Every check runs through the real owner launch chain and the uid drop, with the conformance stand-in; no agy, network, credential or provider call. One local host, after a headroom check; a second-host run is a separate request to the coordinator; never `ai`. Any failing check is STOP: the report says which and how, and the coordinator records it. The report also lists supported configurations as observed or not, for the ordinary-launch follow-up only. Whether a memfd can be a bind source is not assumed. On GO the probe file merges with SL-3; on STOP the report alone is kept.

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

### SL-4 — HOLD-CACHE: retain, prune, clear
- **Scope**: Keep the last two admitted images in a digest-addressed, lock-coordinated cache under the store, and remove them on `clear --all`.
- **Owned files**: `phase-loop-runtime/tests/test_agy_hold_cache.py`
- **Continues**: SL-2's `agy_hold.py`, `agy_qualification.py`, `tests/data/seat_launch_references.json`, `CONTRACTS.md`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-HOLD-2
- **Interfaces consumed**: IF-0-HOLD-1, `agy_hold.retain` (no-op), `admit_seat`
- **Parallel-safe**: no
- **Notes**: Files, tests, run list and stop rules: lanes artifact §G. All mutations take `Store.lock()` and use `dir_fd`; `retain` never waits and never raises. Cache files stay 0600 and are never bound into a jail. The jailed end-to-end cache case is written by SL-3, which follows SL-5.

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
- **Interfaces consumed**: `hold_status`, IF-0-HOLD-1, IF-0-HOLD-2
- **Parallel-safe**: no
- **Notes**: Changes, verification and acceptance: the detailed plan. It is the same on every branch: the doctor prints whatever `ROUTE_COVERAGE` says. Its goals belong to REQUAL and are accepted there.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | (none) | `tests/test_agy_self_qualification.py`, `tests/test_agy_hold.py`, `tests/test_seats_teamhost_doctor.py` | detailed plan, Changes | `pytest tests/test_seats_teamhost_doctor.py -k hold` |
| SL-5.2 | impl | SL-5.1 | `agy_qualification.py`, `doctor.py`, doctor schema and golden | (none) | `pytest tests/test_agy_self_qualification.py -k "expir or legacy or violation"` |
| SL-5.3 | docs | SL-5.2 | `CONTRACTS.md`, card, `TEAM-ONBOARDING.md`, `CHANGELOG.md` | (none) | (none) |
| SL-5.4 | verify | SL-5.3 | detailed plan, Verification | all | detailed plan |

### SL-7 — JAILPROBE2: staged-copy feasibility gate
- **Scope**: Decide, by observed runs on one local host with a stand-in executable and no production change, whether the staged-copy design and its executed-image check work: GO or STOP.
- **Owned files**: `plans/evidence/agyfresh-jailbind-v2-feasibility.md`
- **Interfaces provided**: the v2 feasibility result (GO or STOP)
- **Interfaces consumed**: `seat_jail.build_seat_jail` (pre-existing), `seat_jail.jail_profile_digest` (pre-existing), `plans/evidence/agyfresh-jailbind-feasibility.md` (pre-existing)
- **Parallel-safe**: yes
- **Notes**: Checks V1–V9 and the decision rule: v2 contract §6. Chain checks run through the real owner launch chain and the seat-uid drop, with the unprivileged observer and the conformance stand-in; no agy, network, credential or provider call. dev0 only, after a headroom check, serially under `timeout`; never `ai`. V4 holding with V5 failing is STOP. The report states V8's result (whether the hosted runner can launch a seat jail) in one line, because SL-3's CI obligations depend on it. **Landing:** the report is committed alone and merged by its own evidence-only PR; that file on `main` is what SL-8 and the G-REL clearance cite. The probe cases live in `tests/test_agy_hold_jail.py` on this lane's scratch branch, are not merged here, and are taken over by SL-3.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-7.1 | test | (none) | `tests/test_agy_hold_jail.py` (scratch branch) | probe cases V1–V9 | `pytest tests/test_agy_hold_jail.py -k probe` |
| SL-7.2 | docs | SL-7.1 | `plans/evidence/agyfresh-jailbind-v2-feasibility.md` | (none) | (none) |

### SL-8 — AMEND2: roadmap, contract and HOLD plan amendment
- **Scope**: After the coordinator's GO on SL-7's report, land v2 contract §9 in the roadmap, in AGYFRESH and in the HOLD plan in one docs PR, repin the roadmap's External Inputs row and re-stamp the HOLD plan's frontmatter digest.
- **Owned files**: none
- **Continues**: SL-0's `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyfresh-contract.md`, `plans/phase-plan-v1-agyroll-HOLD.md`
- **Interfaces provided**: the reworded EC-HOLD-13 and IF-0-HOLD-5, the amended AGYFRESH §2.11, SL-3 and SL-6 restored in the HOLD plan
- **Interfaces consumed**: the v2 feasibility result (GO or STOP)
- **Parallel-safe**: no
- **Notes**: Text: v2 contract §9.1 and §9.2, verbatim, for the outcome decided (observed, or custody only). HOLD plan edits: §9.3 with its blocks M1–M9, which supersede the plan's spent branch and checkpoint instructions and move G-REL's evidence reference to SL-7; they were dry-run against the plan as the checkpoint left it. Needs SL-7's report on `main`. Hosted: Gate A, because docs change.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | (none) | roadmap, contract | (none) | `python -m phase_loop_runtime.roadmap_lint specs/phase-plans-agyroll-v1.md` |
| SL-8.2 | docs | SL-8.1 | roadmap, contract, HOLD plan | (none) | `python phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v1-agyroll-HOLD.md` |
| SL-8.3 | verify | SL-8.2 | the three files | (none) | `git diff --check` and both commands above |

### SL-3 — JAILBIND v2: a held admission's standalone Gemini jail runs a staged private copy
- **Scope**: For a held admission, stage a verified private copy of the admitted image under one checked name, bind it in both jails with the existing path bind, gate every held start on the runtime check as decided, write the evidence keys, and clean up on every path; change nothing for ordinary launches, the managed branch, the qualifier or `seat_jail.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_hold_stage.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_agy_hold_jail.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_gemini_seat_egress_1170.py`, `phase-loop-runtime/tests/test_seats_teamhost_integration.py`
- **Continues**: from the HOLD plan's SL-2 and SL-4: `agy_hold.py` (`ROUTE_COVERAGE`), `tests/test_agy_hold_cache.py`, `tests/test_agy_hold.py`, `tests/test_agy_hold_managed.py`, `tests/test_agy_qci.py`, `tests/data/seat_launch_references.json`, `CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`
- **Interfaces provided**: IF-0-HOLD-5
- **Interfaces consumed**: the v2 feasibility result (GO or STOP), the amended AGYFRESH §2.11, `admit_seat` (pre-existing), `agy_hold.ROUTE_COVERAGE` (pre-existing)
- **Parallel-safe**: no
- **Notes**:
  - Files, the modules that are not edited, the two test tiers, stop rules and rollback: v2 contract §7. Requalification and release: §8.
  - Tier 1 (no jail), selected with `-m 'not requires_seat_jail'`, is required in hosted CI, executed with zero skips, unconditionally. Tier 2 (the real owner chain and uid drop, marked `requires_seat_jail`) always runs on dev0 in this lane, with its record going to the G-REL clearance, and is **also required in hosted CI when SL-7's V8 shows the runner can launch a seat jail**; a tier-2 skip is never a pass.
  - The start gate is built for the outcome decided, and only that one: observed, or custody only with no observation at all (v2 contract §7, "What depends on the outcome decided").
  - Both jails are gated: every held production start and retry, and every trusted probe start.
  - The docs this lane writes state the custody basis, the limit of the runtime check and the accepted residual risk in words.
  - Proves, unstubbed, that the managed-dependency jail and every jail `seat_jail_qualification._run_probe_in_jail` builds pass the real canonical guard; writes no qualification pass.
  - From SL-7's report, binding (AGYFRESH §2.11, "Outcome decided"): the observer's ordered launch-chain rule; tier 2 confirms the observer under the real per-seat caps wrapper; the hosted-runner `socat` question is settled by this lane's CI tiers. V8 held, so tier 2 is also required in hosted CI.
  - **Merges only under G-REL.** The PR's first paragraph states the hold and links the three proofs.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | (none) | `tests/test_agy_hold_jail.py`, `tests/test_agy_hold_managed.py`, `tests/test_agy_hold.py` | v2 contract §7 | `pytest tests/test_agy_hold_jail.py -k "ec_hold_13 or ec_hold_14"` |
| SL-3.2 | impl | SL-3.1 | `agy_hold_stage.py` | (none) | `pytest tests/test_agy_hold_jail.py -m 'not requires_seat_jail' -k "staging or gate or sweep or cleanup"` |
| SL-3.3 | impl | SL-3.2 | `panel_invoker.py`, `agy_hold.py`, moved-stub test files, inventory | (none) | `pytest tests/test_agy_hold_jail.py tests/test_agy_hold_managed.py tests/test_gemini_seat_egress_1170.py` |
| SL-3.4 | docs | SL-3.3 | `CONTRACTS.md`, card, `CHANGELOG.md` | (none) | (none) |
| SL-3.5 | verify | SL-3.4 | the frontmatter `suite_command`; `tests/test_panel_invoker.py` as its own run; the tier-2 cases on dev0 | all | the frontmatter `suite_command` |

### SL-6 — Documentation & spec reconciliation
- **Scope**: After the jail lane, confirm the docs each HOLD lane carried agree with what landed, record the spec closeout, and update the plan manifest lifecycle; no code change.
- **Owned files**: `plans/manifest.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-HOLD-5, the v2 feasibility result (GO or STOP)
- **Parallel-safe**: no
- **Notes**: The reducer itself is `no_doc_delta`. Closeout needs every HOLD goal and the release owner's G-REL clearance on SL-3's merged head. In the HOLD plan it also depends on that plan's SL-0, SL-1, SL-2, SL-4 and SL-5 (v2 contract §9.3).

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | (none) | (none) | (none) | the HOLD plan's frontmatter `suite_command` |
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
  SL-2 → SL-4 → SL-3 (one constant). `panel_invoker.py`: SL-3 only in this phase.
  `seat_jail.py`: not edited by any lane. Append-only shared files (`CONTRACTS.md`,
  `CHANGELOG.md`, `tests/data/seat_launch_references.json`): each lane adds its own section
  or rows and keeps the caps lane's `_open_image_fd` row (H6).
- **Handoff H7** is not this phase's work: PROVFWD and ROLLJOB keep `_ExpandedReader` and
  `_bounded_tarinfo`, and ROLLJOB owes streaming for `fetch_member(keep_bytes=True)`. It is
  passed to those phases' plans.
- **Requalification.** agy: none intended; `tests/test_agy_qci.py` decides under AGYFRESH
  §3. Jail: none, because no canonical digest or key changes; EC-HOLD-14 proves it and
  G-REL holds SL-3's merge until it has. The analysis is amendment §2.8–§2.9.
- **Not a lane.** Ordinary jailed launches stay outside HOLD and keep the existing path
  bind; a design that gives them an admitted-image guarantee is separate work.
- **Cost of the jail work.** Two feasibility lanes (SL-1, spent; SL-7), one docs lane
  (SL-8) and the jail lane (SL-3), which adds one module and edits `panel_invoker.py`.
  Disk: one image per held leg while it runs. No extra memory.
- **Not covered, stated in the docs each lane writes.** Managed-release subjects, on every
  route (EC-HOLD-6, second branch). The jailed standalone route until SL-3 merges, and on
  hosts whose state directory fails the staging name rules. Ordinary jailed launches still
  execute a path.
- **Open questions**: lanes artifact §J. None blocks a lane.
- **Stop rule.** As the roadmap's HOLD stop rule: the managed projection, its digest gate,
  the authority path, or any jail property.
- **Rollback.** `[agy] hold = false` per host; every lane reverts with no state migration;
  `clear --all` frees the cache. Reverting SL-3 changes no canonical key.
- **Known destructive changes**: none.
- **Release.** This phase dispatches no release; `CHANGELOG.md` entries go under
  `[Unreleased]`.
- **Effort.** SL-2, SL-3 and SL-5: high. SL-4 and SL-7: medium. SL-0, SL-6 and SL-8: low.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`. EC-HOLD-13, EC-HOLD-14 and EC-HOLD-15 are in the
roadmap as amended.

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
- [ ] EC-HOLD-13 — proven by `pytest tests/test_agy_hold_jail.py -m 'not requires_seat_jail' -k ec_hold_13` executed with zero skips in hosted CI (staging, the name rules, publication and sweeping, the start gate for the outcome decided and its gating, both jails' argv, cleanup, the ordinary launch's argv and one-key evidence); by SL-3's recorded dev0 run of `pytest tests/test_agy_hold_jail.py -m requires_seat_jail`, in which both the production and the probe jail execute the staged copy through the real owner chain; and, if SL-7's V8 showed the hosted runner can launch a seat jail, by that same marker selection executed with zero skips in hosted CI; falsified by a staged copy accepted under a group-writable component or a symlinked spelling, by the two jails binding different strings, by a refused start's output or success evidence being used, by a sweep removing an entry whose launch is still publishing, by a per-launch directory left behind after a cancellation, or by an ordinary launch's argv or evidence differing from the base tree's beyond the one additive key. Path-entered control: through `panel_invoker._prepare_jailed_gemini` and the real `seat_jail.build_seat_jail`, and on dev0 the production owner chain with the executed stand-in reporting its own digest.
- [ ] EC-HOLD-14 — proven by `pytest tests/test_agy_hold_jail.py -k ec_hold_14` executed with zero skips in hosted CI on SL-3's final head, with `plans/evidence/agyfresh-jailbind-v2-feasibility.md`; falsified by any leg's canonical digest or the launch key differing from its base value, or by the managed-dependency jail or a qualifier-built jail failing the real `_require_canonical_jail` against its own leg's digest. Path-entered control: through `seat_jail.build_seat_jail`, `seat_jail_qualification._run_probe_in_jail` and `panel_invoker._require_canonical_jail`, none stubbed.
- [ ] EC-HOLD-15 — proven by `pytest tests/test_agy_hold.py -k ec_hold_15`; falsified by a status that names a candidate for a managed subject, reports the jailed route covered before SL-3, or calls a candidate in use. Path-entered control: through `cli_main` `status`.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyfresh-contract.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `phase-loop-runtime/tests/test_agy_hold.py`, `phase-loop-runtime/tests/test_agy_hold_cache.py`, `phase-loop-runtime/tests/test_agy_hold_managed.py`, `phase-loop-runtime/tests/test_agy_hold_jail.py`, `plans/evidence/agyfresh-jailbind-feasibility.md`, `plans/evidence/agyfresh-jailbind-v2-feasibility.md`
- redaction posture: `metadata_only`
- downstream handling: roadmap amendment (SL-0, text in `plans/artifacts/agyfresh-hold-amendment.md`); release hold G-REL on SL-3; REQUAL's remaining lanes are planned on the amended roadmap after PROVFWD
