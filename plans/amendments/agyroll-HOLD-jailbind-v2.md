---
phase_loop_plan_version: 1
phase: HOLD
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 6c48caeb931380e5da226760f65b2c7790a44ee3a311595dee6f7cff12f190df
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_hold_jail.py tests/test_agy_hold_managed.py tests/test_agy_hold.py tests/test_gemini_seat_egress_1170.py tests/test_seats_teamhost_gemini.py tests/test_seats_teamhost_integration.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# HOLD amendment: JAILBIND v2, a staged private copy for held admissions

## Context

This amends `plans/phase-plan-v1-agyroll-HOLD.md`, which stands at the branch "STOP, new
amendment": its jail lane (SL-3) and reducer (SL-6) were removed after the jail
feasibility lane (SL-1) reported STOP. A sealed memfd cannot be bind-mounted, by any
bubblewrap version or by the kernel. The owner asked for a new design rather than
accepting the gap.

**Proposal for review.** Nothing here is in force until it is accepted and its docs lane
lands. Until then the jailed standalone route refuses a held admission, as today.

**The design** is frozen in `plans/artifacts/agyfresh-jailbind-v2.md` (**v2 contract**,
r3, §1–§10), which this document points at and does not restate:

- For a held admission only, the admitted image is written once per launch to a private
  regular file, verified after writing, mode 0555, under **one checked name**: a spelling
  with no symlink component, every component unwritable by any other uid, used unchanged
  for staging and for both jails' existing path bind (v2 contract §2).
- **The admitted-image guarantee rests on that custody.** The runtime check of the
  provider's executing image is a fail-closed integrity backstop, not an attestation of
  which image ran first (§4). If the unprivileged observer cannot make it, the route is
  custody only: it has no runtime check of the executing image, the contract says so in
  those words, starts are gated by the custody proofs alone (§4.5), and the coordinator
  decides whether that is a GO. Exactly one outcome's text is landed.
- **Accepted window** (coordinator security decision, §3): a wrong image that reached
  `exec` could read its delivered inputs and the stripped bearer copy, make the allowed
  vendor requests and write jail state before it is refused. No in-jail verifier or
  wrapper: that would change the launch chain and is the owner's call.
- `seat_jail.py` is not edited. The bind is the one the profile already declares, so no
  canonical jail digest or qualification key can change (§8).
- Threat model: same uid out of scope; any other uid in scope (§3). Alternatives: §5.

**Unchanged from the accepted HOLD plan.** Held admissions only; ordinary jailed launches
and the managed dependency are untouched; no new refusal code; the release hold G-REL
binds at the jail lane's merge; one local host for feasibility, never `ai`.

**Lane numbers.** The lane grammar takes digits only, so the second feasibility probe is
SL-7 and the second docs lane is SL-8. SL-3 and SL-6 return under their old numbers.

**Relation to the lanes now running.** HOLD-CORE (SL-2), HOLD-CACHE (SL-4) and FAILEXP
(SL-5) proceed under the HOLD plan and do not wait for this amendment. The jail lane goes
after SL-5, because it continues files those lanes also continue.

## Interface Freeze Gates

- [ ] IF-0-HOLD-5 — as reworded by v2 contract §9.2: `agy_hold_stage.stage_image(image)` and its `StagedImage` with `recheck()`; the start gate for the outcome decided (`agy_hold_stage.observe_provider(staged, launch)` when observed, the custody gate of v2 contract §4.5 when custody only); the held branch of `panel_invoker._prepare_jailed_gemini`; and the jailed seat's evidence keys including `provider_image_check`. `seat_jail.build_seat_jail` keeps its signature.

## Lane Index & Dependencies

SL-7 — JAILPROBE2: staged-copy feasibility gate
  Depends on: (none)
  Blocks: SL-8, SL-3, SL-6
  Parallel-safe: yes

SL-8 — AMEND2: roadmap, contract and HOLD plan amendment
  Depends on: SL-7
  Blocks: SL-3, SL-6
  Parallel-safe: no

SL-3 — JAILBIND v2: a held admission's standalone Gemini jail runs a staged private copy
  Depends on: SL-7, SL-8
  Blocks: SL-6
  Parallel-safe: no

SL-6 — Documentation & spec reconciliation
  Depends on: SL-3, SL-7, SL-8
  Blocks: (none)
  Parallel-safe: no

External prerequisites, in the HOLD plan: SL-0 merged (met when the plan PR lands); SL-2
merged before SL-3 starts; SL-5 merged before SL-3 starts. SL-7 needs none of them and can
start on acceptance of this amendment.

**After SL-7** (v2 contract §6, decision table). All of V1, V2, V3, V6 and V7 holding with
V4 and V5 holding: the report recommends GO, observed. V4 holding and V5 failing: STOP. V4
failing: the report recommends neither, and the coordinator decides between GO on custody
only and STOP. Anything else: STOP. SL-8 starts only on the coordinator's recorded GO, and lands the contract
text for the outcome decided. On STOP, SL-8, SL-3 and SL-6 do not run, the owner decides
again, and HOLD lanes artifact §K2 applies if the gap is accepted.

**Execution gate G-REL** applies to SL-3. The release owner (the Agent-Harness Exec) is the
only merge actor. The clearance names the cleared head SHA and links: SL-7's report on
`main`, with its digest comparison and its V8 result; that head's hosted CI run with both
hosted groups executed and zero skips (the EC-HOLD-14 cases and the tier-1 EC-HOLD-13
cases), and tier 2 as well where V8 showed the runner can launch a seat jail; and SL-3's
recorded dev0 run of the tier-2 cases. The merge is head-conditioned on that SHA, after all required checks pass on it; no
auto-merge and no queued merge.

## Lanes

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
- **Owned files**: `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyfresh-contract.md`, `plans/phase-plan-v1-agyroll-HOLD.md`
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

Per lane: v2 contract §6 (SL-7) and §7 (SL-3). Whole amendment: the frontmatter
`suite_command`, with `tests/test_panel_invoker.py` as its own run.

Shared-host rule: the listed files only, serially without `-n`, under `timeout`, after a
headroom check; never a full suite. Hosted CI before each merge: the full pytest job, the
`agy catalog contract` job, and, because `panel_invoker.py` changes, the strict
conformance run and `--release` check from the roadmap's Verification section; Gate A
where docs change. No live provider call and no jail qualification run on a host is part
of any lane.

## Execution Notes

- **Execution.** One implementer and one PR per lane, in the order SL-7 → SL-8 → SL-3 →
  SL-6. SL-7 may run beside the HOLD plan's SL-2, SL-4 and SL-5; it shares no file with
  them.
- **Single-writer files.** `panel_invoker.py`: SL-3 only in this phase. `agy_hold.py`:
  the HOLD plan's SL-2 → SL-4, then SL-3 (one constant). `seat_jail.py`: nobody.
- **Requalification.** Jail: none is possible by construction, and EC-HOLD-14 proves it.
  agy: none intended; `tests/test_agy_qci.py` decides. A source-hash update for
  `panel_invoker.py` is expected.
- **Cost.** Disk: one image per held leg while it runs. Time: one write and three reads of
  the image per held launch. Two lanes of code and tests (SL-7 medium, SL-3 high).
- **Not covered after this amendment.** Managed-release subjects. Ordinary jailed launches
  still execute a path. Hosts whose state directory fails the staging name rules. A wrong
  image that reaches `exec` is refused after the fact, not prevented (v2 contract §3).
- **Open questions**: v2 contract §10.
- **Stop rule.** As the roadmap's amended HOLD stop rule: the managed projection, its
  digest gate, the authority path, or any jail property.
- **Rollback.** Revert SL-3; `seat-images/` may be deleted at any time.
- **Known destructive changes**: none.
- **Release.** This amendment dispatches no release; `CHANGELOG.md` entries go under
  `[Unreleased]`.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`. Only the two goals this amendment restores are
listed; the HOLD plan carries the others. EC-HOLD-13 is proven against its reworded text
(v2 contract §9.2), which SL-8 lands.

- [ ] EC-HOLD-13 — proven by `pytest tests/test_agy_hold_jail.py -m 'not requires_seat_jail' -k ec_hold_13` executed with zero skips in hosted CI (staging, the name rules, publication and sweeping, the start gate for the outcome decided and its gating, both jails' argv, cleanup, the ordinary launch's argv and one-key evidence); by SL-3's recorded dev0 run of `pytest tests/test_agy_hold_jail.py -m requires_seat_jail`, in which both the production and the probe jail execute the staged copy through the real owner chain; and, if SL-7's V8 showed the hosted runner can launch a seat jail, by that same marker selection executed with zero skips in hosted CI; falsified by a staged copy accepted under a group-writable component or a symlinked spelling, by the two jails binding different strings, by a refused start's output or success evidence being used, by a sweep removing an entry whose launch is still publishing, by a per-launch directory left behind after a cancellation, or by an ordinary launch's argv or evidence differing from the base tree's beyond the one additive key. Path-entered control: through `panel_invoker._prepare_jailed_gemini` and the real `seat_jail.build_seat_jail`, and on dev0 the production owner chain with the executed stand-in reporting its own digest.
- [ ] EC-HOLD-14 — proven by `pytest tests/test_agy_hold_jail.py -k ec_hold_14` executed with zero skips in hosted CI on SL-3's final head, with `plans/evidence/agyfresh-jailbind-v2-feasibility.md`; falsified by any leg's canonical digest or the launch key differing from its base value, or by the managed-dependency jail or a qualifier-built jail failing the real `_require_canonical_jail` against its own leg's digest. Path-entered control: through `seat_jail.build_seat_jail`, `seat_jail_qualification._run_probe_in_jail` and `panel_invoker._require_canonical_jail`, none stubbed.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `roadmap_amendment`
- target surfaces: `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyfresh-contract.md`, `plans/phase-plan-v1-agyroll-HOLD.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- evidence paths: `phase-loop-runtime/tests/test_agy_hold_jail.py`, `plans/evidence/agyfresh-jailbind-v2-feasibility.md`
- redaction posture: `metadata_only`
- downstream handling: roadmap amendment (SL-8, text in `plans/artifacts/agyfresh-jailbind-v2.md` §9); release hold G-REL on SL-3
