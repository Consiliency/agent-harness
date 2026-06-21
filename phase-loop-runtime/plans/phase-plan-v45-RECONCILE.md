---
phase_loop_plan_version: 1
phase: RECONCILE
roadmap: specs/phase-plans-v45-phaseloop-runner-hardening.md
roadmap_sha256: 5ae8ff949bafb35775cf64b5f156c7b013e1bf156d013a086f20e84875edc9bd
---

# RECONCILE — git-reality reconciliation (IF-0-RECONCILE-1)

## Context

FOUND shipped `reconcile_against_git_reality` as a no-op. This phase implements
the real body so a phase that was planned+executed+merged under roadmap `vN`,
then carried forward into a byte-identical section under `vN+1` (a rename/advance,
not an edit), classifies as `complete` instead of `unplanned` — preventing a
redundant re-plan into a divergent filename.

**Why the prior attempt was deferred (and how this fixes it).** Promoting purely
on "a completion commit with the plan SHA exists in history" is unsafe: a
completion commit proves the work was done *once*, not that it still exists. A
later `git revert` leaves the roadmap section SHA unchanged, so the phase would be
falsely promoted → the runner skips it → the reverted work is never recreated
(criterion-4 violation). This plan closes that gap by additionally requiring the
phase's **own owned files to still be present at HEAD unchanged since the closeout
commit** — a git-detectable revert signal.

## Meta / safe cutover

This modifies `classify_phase`, the universal classifier every phase-loop run on
this repo depends on. To contain blast radius while landing on our own runtime,
the active behavior is gated behind `PHASE_LOOP_RECONCILE_GIT_REALITY` (default
**off** → identity no-op = today's behavior). The PR lands inert; we flip the flag
deliberately after validation. (Contrast: existing flags default on; this one is
opt-in precisely because it is the cutover point.)

## Interface Freeze Gates

- **IF-0-RECONCILE-1** — `reconcile_against_git_reality(repo, roadmap, classifications) -> dict[str,str]`
  promotes phase P (only when currently `unplanned`) to `complete` iff ALL hold,
  else leaves it untouched (never demotes):
  1. a completion commit C reachable from HEAD has **parsed trailers**
     `Plan: <plan resolving to P>` and `Terminal-Status: complete`;
  2. P's section in the current roadmap is byte-identical (`phase_sha256`) to its
     section at C (rename/advance, not edit);
  3. every owned file in P's plan at C is unchanged between C and HEAD
     (`git diff --quiet C HEAD -- <owned patterns>`) — reverted/modified work
     blocks promotion.
  Gated by `PHASE_LOOP_RECONCILE_GIT_REALITY` (default off → no-op).
  `classify_phase` consults the same shared predicate before returning `unplanned`.

## Lanes

### SL-1 — reconcile core + cutover flag (contract)
- **Scope**: implement the safe reality check + the opt-in flag.
- **Owned files**: `vendor/phase-loop-runtime/src/phase_loop_runtime/discovery.py`, `vendor/phase-loop-runtime/src/phase_loop_runtime/pipeline_adapter/flag.py`
- **Interfaces provided**: `reconcile_against_git_reality` (real body), `_phase_complete_in_git_reality` (shared predicate), `reconcile_git_reality_enabled`
- **Interfaces consumed**: `phase_sha256`, `parse_plan_ownership`, `PLAN_RE`, `find_plan_artifact`
- **Tasks**: test → impl → verify.

### SL-2 — classifier consultation (single writer: classifier.py)
- **Scope**: `classify_phase` consults the shared predicate before returning `unplanned`, gated by the flag.
- **Owned files**: `vendor/phase-loop-runtime/src/phase_loop_runtime/classifier.py`
- **Interfaces consumed**: `_phase_complete_in_git_reality`, `reconcile_git_reality_enabled`
- **Depends on**: SL-1

### SL-3 — scenario tests (revert test is the proof obligation)
- **Owned files**: `vendor/phase-loop-runtime/tests/test_phase_loop_v45_reconcile.py`
- **Depends on**: SL-1, SL-2

## Single source of truth

All three conditions live in `discovery._phase_complete_in_git_reality`; both
`classify_phase` and `reconcile_against_git_reality` call it, so the two entry
points cannot drift into different safety postures.

## Scope assumption (explicit)

Reconcile promotes on the *phase's own* artifacts persisting, not global repo
consistency. A reverted **dependency** owned by a different phase is verification's
job, not reconcile's.

## Acceptance criteria

- [ ] Renamed (byte-identical section) + work-present → `complete`.
- [ ] **Renamed + owned file reverted → stays `unplanned`** (B1 proof obligation).
- [ ] Edited section → stays `unplanned` (criterion 4).
- [ ] No completion commit → stays `unplanned`.
- [ ] `Terminal-Status` matched as a parsed trailer, not a substring (B2).
- [ ] Never demotes a `complete`/`blocked` phase.
- [ ] Flag **off** (default) → pure no-op even when a completion commit exists (cutover proof).
- [ ] Full suite green; `--phase-scheduler concurrent` reclassification (deferred in SCHED #57) now covered.

## Verification

```sh
cd vendor/phase-loop-runtime
PYTHONPATH=src python3 -m pytest tests/test_phase_loop_v45_reconcile.py -q
PYTHONPATH=src python3 -m pytest -q   # full suite
```
