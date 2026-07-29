# Phase roadmap v10 — Review Integrity, Contract Conformance, and Debt Retirement

> **Status (2026-07-29): ACTIVE — created this date, nothing executed yet.**
> Completion is recorded in the ledger, NOT by ticking these boxes (see `EC-LEGIBLE-1`,
> which exists to fix exactly that). Do not read unchecked boxes as "unstarted".

## Context

A single session on 2026-07-28/29 surfaced three overlapping problems that were previously
invisible, and this roadmap sequences their resolution.

**The review instrument under-reports.** The cross-vendor board is this repo's merge gate, yet
three real pre-merge boards each returned 3 reviewing seats against a declared floor of 3 with
`native_fill_requests: 0` and **no degradation signal to the caller**. `Seat.lens` has "no
behavior yet" (`advisor_board/schema.py:178`) — the lens never reaches the reviewer's prompt
(`panel_invoker.py:4111`) — while ratification counts it as coverage
(`ratification_policy.py:173`). One seat returned AGREE on four consecutive reviews while
disclosing it opened no source files; on one of those, two seats approved a change that fails CI
on five gates.

**Proofs that cannot fail.** Six independent instances in one session: tautological tests
(ah#299), a pre-existing test *asserting* the data loss a fix was written to prevent (ah#354), a
mutation that silently failed to apply, `Mutation:` comments naming mutations that do not kill
their tests, and — in a plan written specifically to prevent this — three distinct vacuity forms
(a falsifier that cannot fire, an assertion reading the wrong observable, and a scenario whose
precondition fails silently so the falsifier dies in BOTH arms).

**Contract divergence, concealed by self-authored fixtures.** Our outside-agent validator accepts
a different dialect than the contract it pins to — three of nine top-level fields overlap, and the
canonical valid work-request is rejected with ten blockers. It stayed invisible because every test
used fixtures we wrote ourselves, and governed-pipeline's real gate feeds our dialect to the CLI,
so the conformance fence passes while never exercising the canonical corpus.

**The dominant defect class: MERGED IS NOT REACHABLE.** Five independent instances, all
found by reading code against intent rather than by any test or checkbox — a guard correct but
unwired at both construction sites (`epoch_blocked`); a primitive built with its consumer never
threaded (readmit); a shortcut permanently dormant behind a `False` flag (FAB delta review); a
repair loop that only test-injected closures ever exercise (`apply_fix=None`); and two board
backings built, wired into the seam, unit-tested, and constructed by zero production callers
(ABDOMNI, ABDOBS). In every case the suite was green and the work looked done. Several exit
criteria in this roadmap therefore assert REACHABILITY explicitly, because "merged" has
repeatedly failed to imply it.

Underneath all three sits a legibility failure: seven roadmaps across four repos report **zero**
completed criteria, while audits show governed-pipeline v26 is 28/28 delivered and v33 is 46/51.
A finished roadmap and an unstarted one are indistinguishable by reading.

## Assumptions (fail-loud if wrong)

1. `Consiliency/spec` PR #102 remains unmerged; our contract pin (`c1085483`) is therefore
   unsatisfiable from merged sources. CONFORM's pin work is externally gated (`spec#118`).
2. `governed-pipeline` continues to pin agent-harness 0.5.0 while we ship 0.7.13 until it acts on
   `governed-pipeline#128`. No phase here depends on that being resolved.
3. The claude board seat remains structurally unavailable inside Harness Code
   (`tui_adapter_required`) until REVIEWTRUTH lands. Every review in this roadmap runs 3-of-4 and
   must be recorded as such.
4. `plans/manifest.json` is load-bearing for roadmap discovery; a malformed entry has previously
   disabled discovery entirely (fixed per-entry in #170).
5. The ratified ah#363 decision stands: all admission kinds draw from ONE shared monotonic epoch
   allocator, and publish byte-neutrality is RETRACTED.

## Non-Goals

- Sequencing work in `spec`, `governed-pipeline`, or `consiliency-portal`. We do not own those
  repos. The four-repo outside-agent release train
  (`governed-pipeline/specs/outside-agent-release-train-v1.md`) is the coordination mechanism;
  this roadmap declares external dependencies and does not schedule other teams.
- Re-litigating ah#363 (epoch domains) or the ah#354 GC design fork — both are decision records.
- Publishing to PyPI/npm. Release dispatch remains user-gated.
- Building native-fill for TUI-policy claude seats. That boundary is deliberate.

## Cross-Cutting Principles

1. **Every acceptance criterion names a falsifier that was RUN**, with the injection anchor
   asserted (`assert <anchor> in <source>`). An unapplied mutation is indistinguishable from a
   passing one.
2. **A falsifier must name the OBSERVABLE the assertion reads** — a raise, a value, a sequence, a
   count. "It fails" is insufficient; "it raises X" is wrong when the real signal is a value.
3. **An assertion of the form "X did not happen" must prove its path was ENTERED.** Absence of a
   bad outcome is not evidence when the scenario may never have reached the seam.
4. **Run mutations per-parameter, not per-file.** File-level "the mutation kills tests" hides a
   surviving parameter.
5. **When a decision changes a signature or contract, grep EVERY occurrence and record which
   sections were checked.** A decision present in only some sections reads as settled and is
   therefore more dangerous than an open one.
6. **Claim only what you are positioned to claim.** Understating is as wrong as overstating; a
   record must not assert facts about work it did not perform.
7. Every board verdict records how many seats actually REVIEWED, not merely how many responded.
8. **Dispatch comes from a registry, never a hardcoded branch.** (from `north-star-pi-native`)
9. **Tool naming is per-MODEL, not per-vendor.** (from `north-star-pi-native`)
10. **Provider backings are swappable — TUI today does not imply TUI forever.** (from `north-star-pi-native`)
11. **Session capture is a first-class output, not a debugging by-product.** (from `north-star-pi-native`)

## Top Interface-Freeze Gates

- **IF-0-LEGIBLE-1** — a roadmap status contract: the field/section that declares
  `active | delivered | superseded`, and the runtime accessor that reads it.
- **IF-0-REVIEWTRUTH-1** — the typed per-seat outcome (`reviewed | unavailable | errored`) carried
  on `PanelLegResult`, distinct from its `text` payload, plus the reviewed-seat count exposed to
  ratification.
- **IF-0-PROOFGATE-1** — the acceptance-item grammar
  `- [ ] EC-<ALIAS>-<N> — proven by <command>, falsified by <mutation>` and the evidence record
  shape written alongside `verification.json`.
- **IF-0-CONFORM-1** — the vendored canonical contract surface: schema files, vector manifest, and
  the per-file digest record that guards drift.
- **IF-0-FABPUB-1** — `make_request(epoch, attempt_id)` and the enforced equalities
  (`request.lease_epoch == epoch`, `request.attempt_id == attempt_id`), plus the commit-stable
  approval identity resolution.


## Absorbed Roadmaps (bookkeeping — this roadmap SUPERSEDES these)

This roadmap absorbs the live work of the roadmaps below. Each is closed out with a
supersession banner pointing here. **Nothing was dropped**; where a phase was already
delivered it is recorded as such rather than re-scheduled.

| absorbed roadmap | disposition | where its live work went |
|---|---|---|
| `phase-plans-convergence-v1.md` | SUPERSEDED (had maintainer RESUME 2026-07-26) | FREEZE→LEGIBLE (the #312 status contradiction); RUNTIME→RUNTIME + REVIEWTRUTH (its advisor-seat criterion); BROKER→FABPUB/FABREADMIT; INTEG/FAULTS/PILOT/RELEASE carried forward as phases |
| `phase-plans-v7.md` (Outside-Agent Conformance) | SUPERSEDED | OAMOCK delivered (no carry); OACORE-3 + OAREAL-2 → CONFORM; OACONTRACT + OARELEASE → CONFORM, externally gated on `spec#118` |
| `phase-plans-v6.md` | **DELIVERED — closed, not absorbed** | Nothing carried: all 5 phases shipped (#114 via #115/#116/#118, 27 tests green). Closed with a DELIVERED banner, a distinct disposition from superseded. |
| `phase-plans-v1.md` | **DELIVERED — closed** | Nothing carried; 7 phases shipped via #3, released v0.1.4 |
| `phase-plans-v1-task-message-sourcebroker.md` | **DELIVERED — closed** | Nothing carried; shipped `bf7d5e0` (#168) + hardening #176–#190 |
| `phase-plans-cross-repo-v1.md` | **DELIVERED — closed** | Nothing carried; 5 phases shipped `5423486` (#35/#29). Its MVP non-goals (parallel DAG-of-DAGs, auto-revert, content-hash identity) are FUTURE scope, deliberately not carried |
| `north-star-pi-native.md` | **RETAINED — not a roadmap, not closed** | Vision + gated backlog; authorizes nothing. Its 4 principles folded into this roadmap's Cross-Cutting Principles (8–11); its 6 backlog gates stay there as candidates |
| `phase-plans-v9.md` | **SUPERSEDED — ABSORBED** | 4 of 5 phases DELIVERED (#238/#243/#231, #244/#245, #250, #91). ONE live phase: FAB agent-harness#191 delta review, dormant because `_FAB_DELTA_BROKER_READMIT_READY=False`. Carried into FABREADMIT as EC-FABREADMIT-6/7 |
| `phase-plans-v8.md` | **DELIVERED — closed** | Nothing carried; EXECREG/GROKEXEC/AUTOSEL/DISSECT all shipped (#144/#148/#150/#152/#142) |
| `phase-plans-v3.md` (model-routing-v2) | **SUPERSEDED — ABSORBED** | 3 of 4 phases DELIVERED. Live gap: the governed pre-merge fix-round is not wired in production → EC-REVIEWTRUTH-8 |
| `phase-plans-v2.md` (model-routing-v1) | **SUPERSEDED — ABSORBED** | 4 of 5 phases DELIVERED. Same single live gap as v3 → EC-REVIEWTRUTH-8. Shipped effort defaults (`execute/repair=high`, `review=max`) intentionally differ from the doc under #310 — a reconciliation, not a delivery gap |
| `phase-plans-v5.md` (Advisor Board) | **SUPERSEDED — ABSORBED** | Phases 1–4 and 7 DELIVERED. ABDOMNI + ABDOBS are built, wired and unit-tested but have ZERO production constructors → EC-LEGLIFE-6/7. Residual: a stale `skills_bundle/codex-advisor-panel/` duplicate survives bundle regeneration |
| `phase-plans-v4.md` (Advisor Panel ownership) | **DELIVERED — closed** | Nothing carried; all 6 phases shipped `9de824d`/`61f41c6`, focused slice 46/0 today. Three deliberate supersessions recorded in its banner (fable-5 leg default, gemini-3.6-flash, panel→board rename) so they are not mistaken for regressions | Assessment running; any live phase will be appended here before those roadmaps are closed. **Do not close them until that lands.** |

**Overlap that motivated the absorption** — three roadmaps independently covered the same work:
`convergence-v1` RUNTIME criterion 4 ("advisor-seat lifecycle persists complete per-seat
outcomes") is this roadmap's REVIEWTRUTH; `convergence-v1` BROKER is FABPUB/FABREADMIT; `v7` is
CONFORM. A v10 written without absorbing them would have been a fourth parallel effort.

## Phases

### Phase 0 — Roadmap and Manifest Legibility (LEGIBLE)

**Objective**
Make a roadmap able to report its own state, so that every later phase in this document is
trackable and a delivered roadmap is distinguishable from an abandoned one.

**Exit criteria**
- [ ] EC-LEGIBLE-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-LEGIBLE-1 — Given only the repo, each roadmap's state (`active | delivered | superseded`) is determinable WITHOUT querying the ledger; falsified by removing the mechanism and finding 12 of 13 roadmaps still report correctly
- [ ] EC-LEGIBLE-2 — `select_roadmap`'s chosen roadmap is identifiable from the repo without executing it
- [ ] EC-LEGIBLE-3 — A plan file present on disk but absent from `plans/manifest.json` is reported by a check, not silently invisible to discovery
- [ ] EC-LEGIBLE-4 — agent-harness#347 is merged, its PR body citing only commits present in its head's ancestry
- [ ] EC-LEGIBLE-5 — The `.claude/docs-catalog.json` scaffold either gains its rescan implementation or is removed; an empty catalog no longer reads as a populated one

**Scope notes**
Decompose into 3 lanes over disjoint files: lane A owns the roadmap status contract and its
runtime accessor; lane B owns the manifest presence check; lane C owns agent-harness#347 and the
docs-catalog disposition. Lane A publishes IF-0-LEGIBLE-1 on day 1 so lane B can consume the
accessor shape before its implementation lands.

**Non-goals**
Reconciling the 284 open checkboxes across v1–v9. Classifying those is separate work that this
phase makes possible.

**Key files**
- `specs/phase-plans-v*.md`
- `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`
- `phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py`
- `.claude/docs-catalog.json`

**Depends on**
- (none)

**Produces**
- IF-0-LEGIBLE-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `roadmap_amendment`; target surfaces:
`specs/**`, `plans/manifest.json`; evidence paths: metadata-only refs to the roadmap status field;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 1 — Board Reports Its Own Degradation (REVIEWTRUTH)

**Objective**
Stop the cross-vendor board silently losing seats. Carry a typed per-seat outcome distinct from
`text`, enforce the reviewed-seat floor, and make `Seat.lens` actually reach the reviewer.

**Exit criteria**
- [ ] EC-REVIEWTRUTH-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-REVIEWTRUTH-1 — A board below its declared REVIEWED-seat floor cannot report convergence; falsified by removing the check and re-running the three 2026-07-28 boards, which must then still be blocked
- [ ] EC-REVIEWTRUTH-2 — An unusable leg is distinguished from a reviewing leg WITHOUT inspecting `text`; falsified by reverting to the `text.strip()` predicate
- [ ] EC-REVIEWTRUTH-3 — A spawn that RAISES does not produce a governed BLOCK from its traceback
- [ ] EC-REVIEWTRUTH-4 — A board driven inside Harness Code yields either 4 reviewing seats or a typed unfillable signal; a silent 3-of-4 is impossible
- [ ] EC-REVIEWTRUTH-5 — `Seat.lens` reaches the reviewer's prompt, and ratification counts lens coverage only for seats whose prompt carried it
- [ ] EC-REVIEWTRUTH-6 — `test_advisor_board_golden.py` still passes, or its sanctioned-delta list is explicitly and normatively amended
- [ ] EC-REVIEWTRUTH-7 — A capped or empty leg is distinguishable from a leg that reviewed and found nothing, and is retried rather than counted
- [ ] EC-REVIEWTRUTH-8 — **The governed pre-merge auto-repair fix-round is WIRED IN PRODUCTION.** Build an `apply_fix` closure reusing `_build_repair_context` (`runner.py:6931`) + `build_prompt` + `launch_with_spec` to re-dispatch `repair` with the panel's `block` findings folded into `repair_context`, re-render the bundle from the new staged diff, and pass it — not `None` — at `runner.py:10140`. Falsified by reverting to `apply_fix=None`, after which a governed run with a mock panel returning block-then-pass must NOT become mergeable. Positive control: the phase becomes mergeable within `max_rounds` (default 3), with the governed fix-round counter kept independent of `_recent_repeated_repair_failures`. (Absorbed from v3 P1 / v2 P3 — the loop machinery exists at `governed_premerge.py:371-373` and is exercised only by test-injected closures; the omission is deliberate and self-documented at `runner.py:9748-9757`.)

**Scope notes**
Decompose into 4 lanes: lane A owns the typed outcome on `PanelLegResult` and publishes
IF-0-REVIEWTRUTH-1 day 1; lane B owns `governed_review._findings_from_panel` consuming it; lane C
owns lens threading into the prompt plus the ratification coverage rule; lane D owns composition
(fillable seat vs lens-distinct backfill) and the typed unfillable signal. `panel_invoker.py` is a
single-writer file — lanes A and D must partition it by function or serialize.

**Non-goals**
Per-repo custom seats and RISCO lenses (LEGLIFE). Leg lifecycle and timeouts (LEGLIFE).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/schema.py`
- `phase-loop-runtime/tests/test_advisor_board_golden.py`

**Depends on**
- (none)

**Produces**
- IF-0-REVIEWTRUTH-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 2 — Falsifier Gate (PROOFGATE)

**Objective**
Extend the existing plan grammar so an acceptance criterion binds to a falsifier, not only a proof
command — and so the three vacuity forms observed on 2026-07-28/29 are mechanically rejected.

**Exit criteria**
- [ ] EC-PROOFGATE-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-PROOFGATE-1 — An acceptance item lacking a `falsified by` clause is REJECTED by the plan validator; falsified by removing the clause check, after which a falsifier-less plan validates
- [ ] EC-PROOFGATE-2 — Recorded mutation evidence whose injection anchor did NOT match is reported as `mutation_not_applied`, never as a pass
- [ ] EC-PROOFGATE-3 — Re-running the validator against ah#358's ORIGINAL acceptance criteria rejects them, since they could not have fired on any motivating incident
- [ ] EC-PROOFGATE-4 — A falsifier for a guard must target the PRODUCTION CONSTRUCTION SITE, not only the helper; falsified by unwiring `epoch_blocked` and finding every test still passes
- [ ] EC-PROOFGATE-5 — A parametrized falsifier must be shown to kill EVERY parameter; a surviving parameter is reported
- [ ] EC-PROOFGATE-6 — An acceptance item asserting "X did not happen" must declare its path-entered control
- [ ] EC-PROOFGATE-7 — Legacy plans predating this grammar are grandfathered explicitly, not silently failed

**Scope notes**
Decompose into 3 lanes: lane A owns the grammar and validator check (extends check P alongside the
existing check E test-before-impl); lane B owns the mutation-evidence record shape and its
`mutation_not_applied` state, publishing IF-0-PROOFGATE-1 day 1; lane C owns the grandfathering
rule and the regression corpus of known-bad criteria (ah#358 originals, ah#288 AC-1/AC-4). Warn
level by default, per the standing autonomy-first guardrail — checks G and K are the precedent.

**Non-goals**
Granting review legs execution capability. Review bundles are attacker-controlled by construction;
that boundary stays closed and panels audit mutation ADEQUACY instead.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/claude-plan-phase/scripts/validate_plan_doc.py`
- `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`
- `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`

**Depends on**
- (none)

**Produces**
- IF-0-PROOFGATE-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `dotfiles_skill_source_update`; target
surfaces: `skills-src/**`, the regenerated skills bundle; evidence paths: metadata-only refs to
the amended grammar; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 3 — Canonical Contract Conformance (CONFORM)

**Objective**
Make our outside-agent validator read the contract it claims to conform to, and reconcile the pin
so "vectors from spec" means the spec's vectors.

**Exit criteria**
- [ ] EC-CONFORM-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-CONFORM-1 — The canonical corpus runs through `outside-agent-validate` and the 3 canonical VALID vectors pass; falsified by restoring the pre-#371 allow-list, which must reject them
- [ ] EC-CONFORM-2 — No path emits a submitter-supplied value into serialized output; falsified independently for each projection channel, with the complete channel enumeration recorded and its method stated
- [ ] EC-CONFORM-3 — `redaction_posture="metadata_only"` is emitted only where something enforces it
- [ ] EC-CONFORM-4 — The vendored corpus cannot drift silently from its recorded source digests
- [ ] EC-CONFORM-5 — `outside_agent_pin.py` records a per-schema content digest, so a byte change preserving `…v0.1` is detected
- [ ] EC-CONFORM-6 — agent-harness#specs/phase-plans-v7 OACORE-3 and OAREAL-2 are either satisfiable against the merged contract or explicitly recorded as externally blocked

**Scope notes**
Decompose into 2 lanes: lane A owns the validator dialect, redaction separation, and the
projection-channel enumeration (agent-harness#372 is in flight); lane B owns the pin digest work
and the v7 criterion disposition. **EC-CONFORM-5 and EC-CONFORM-6 are EXTERNALLY GATED on
`Consiliency/spec` PR #102 (`spec#118`)** — lane B may prepare but must not close them while the
contract is unmerged and unpublished.

**Non-goals**
Landing governed-pipeline's real-gate fixture alignment. That is theirs
(`governed-pipeline#128`).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_schema.py`
- `phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_core.py`
- `phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_vectors.py`
- `phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_pin.py`
- `phase-loop-runtime/src/phase_loop_runtime/conformance/_contract/`

**Depends on**
- (none)

**Produces**
- IF-0-CONFORM-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`; target surfaces:
the vendored `_contract/` surface and the pin; evidence paths: metadata-only digest refs;
`redaction_posture: metadata_only`; missing evidence routes non-human
`blocker_class=contract_bug`. Downstream `mirror_cutover_required` is a metadata-only deferral,
never write authorization.

### Phase 4 — Shared Epoch Allocator: Publish Identity (FABPUB)

**Objective**
Migrate publish onto the shared monotonic allocator, solving publish's identity under a commit
that moves HEAD mid-operation. This is where the density is.

**Exit criteria**
- [ ] EC-FABPUB-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-FABPUB-1 — A publish presenting a stale epoch against a higher-water store is refused; falsified by the `admit()`-revert form, whose observable is the raise
- [ ] EC-FABPUB-2 — `admit_next` ENFORCES `request.lease_epoch == epoch`; falsified by removing the guard, whose observable is a record with divergent `epoch`/`lease_epoch`, not a raise
- [ ] EC-FABPUB-3 — `admit_next` ENFORCES `request.attempt_id == attempt_id`; falsified by a factory ignoring the supplied id so `lease()` defaults to `uuid4`
- [ ] EC-FABPUB-4 — A faithful post-crash publish retry DEDUPS rather than re-allocating; falsified by a captured-closure model that masks HEAD drift
- [ ] EC-FABPUB-5 — A legitimate post-crash retry is NOT rejected by the conflict comparison; this is the failure mode the round-2 fix introduced
- [ ] EC-FABPUB-6 — A conflicting resume (same attempt_id, different authority) is REFUSED; positive control: a genuine same-fields resume still dedups
- [ ] EC-FABPUB-7 — Publish byte-neutrality is explicitly RETRACTED in the CHANGELOG, not claimed alongside renumbering

**Scope notes**
Decompose into 3 lanes: lane A owns the allocator and its enforced equalities, publishing
IF-0-FABPUB-1 day 1; lane B owns the publish-path seams (S1/S3/S3b) consuming that contract; lane
C owns the commit-stable approval identity sub-design (§5b), which is the open design question and
should not gate the other two. `train_runner.py` is a single-writer file — lanes B and C must
partition by function. The §10 test-first contract applies: wave-0 tests land red against `main`
before any production change.

**Non-goals**
The readmit consumer and the flag flip (FABREADMIT). The FAB review-round `epoch` namespace, which
is a different `epoch` and out of scope.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/admission.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py`
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/publishing.py`

**Depends on**
- (none)

**Produces**
- IF-0-FABPUB-1

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 5 — Shared Epoch Allocator: Readmit Consumer (FABREADMIT)

**Objective**
Wire the delta-readmit consumer through the broker and flip the engagement flag, on a base where
publish is already migrated so the mixed-allocation interlock is a merge boundary rather than an
in-plan promise.

**Exit criteria**
- [ ] EC-FABREADMIT-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-FABREADMIT-1 — Both readmit commit points converge on ONE broker-gated path; falsified by restoring either direct append
- [ ] EC-FABREADMIT-2 — A revoked FRESH delta re-admit does not merge; the assertion is the desired behaviour and is paired with a non-revoked reachability control proving the seam was entered
- [ ] EC-FABREADMIT-3 — A revoked CRASH-RESUME re-admit does not merge; same pairing, targeting the early append specifically
- [ ] EC-FABREADMIT-4 — The engagement flag cannot be enabled while any publisher still stamps a hardcoded epoch
- [ ] EC-FABREADMIT-5 — The enumeration of head-advancing append sites is recorded with a re-runnable method, so a future third site is detectable
- [ ] EC-FABREADMIT-6 — **The delta-review shortcut ACTUALLY ENGAGES.** `_FAB_DELTA_BROKER_READMIT_READY` is flipped True and `fab_delta_shortcut_enabled()` returns True under production conditions, proven by an end-to-end test in which the shortcut FIRES — not merely that it is permitted to. Falsified by reverting the flag, after which that test must fail. **Note: EC-FABREADMIT-4 is a NEGATIVE-ONLY criterion — "the flag cannot be enabled prematurely" is satisfied by never enabling it, which would leave agent-harness#191 permanently dormant. This criterion supplies the positive case.**
- [ ] EC-FABREADMIT-7 — agent-harness#191 (FAB delta review with reviewed-byte equivalence) is closeable: the consumer merged DORMANT in `ecd1258` is live, and the reviewed-byte-equivalence shortcut runs on a real delta

**Scope notes**
Two lanes: lane A owns the unified commit path and the consumer seam; lane B owns the flag-flip
interlock and its ordering guarantees. Wave-0 tests here must be red against a FABPUB-merged
`main`, not against today's `main` — the bypass still exists at that point, which is what makes
them red.

**Non-goals**
Publish identity. That is FABPUB and must be merged first.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`

**Depends on**
- FABPUB

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 6 — Scheduler and Worktree Reclamation (SCHED)

**Objective**
Reclaim crash-residual worktrees without destroying recoverable work, and close the lane-scheduler
dispatch cluster.

**Exit criteria**
- [ ] EC-SCHED-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-SCHED-1 — A worktree preserved by the GC is NOT destroyed by the recreation path eight lines later; falsified by restoring the unconditional force-remove
- [ ] EC-SCHED-2 — `test_create_is_idempotent_after_stale_worktree` no longer pins data loss as intended behaviour, and its replacement assertion is recorded as a ratified decision
- [ ] EC-SCHED-3 — A worktree whose only content is a gitignored handoff is not treated as empty
- [ ] EC-SCHED-4 — The lane scheduler honours `work_unit_kind`, so a reducer lane is not dispatched as an executor
- [ ] EC-SCHED-5 — Validated planner artifacts survive parent reduction under `--phase-scheduler concurrent`
- [ ] EC-SCHED-6 — After a no-diff concurrent dispatch, the parent does not run phase verification against files that were never created

**Scope notes**
Decompose into 2 lanes over disjoint files: lane A owns worktree reclamation
(`phase_worktree_executor.py`), lane B owns the scheduler cluster (`lane_scheduler.py`,
`runner.py`) for which a drafted plan already exists. **EC-SCHED-1/2/3 are BLOCKED on the ah#354
design fork**, which has been paneled twice — options (a)/(b)/(c) were rejected 3/3, and
resume-first was rejected on mechanism (the handoff is a closeout artifact, not a session
checkpoint). A third framing is required before lane A starts.

**Non-goals**
Building a session-checkpoint mechanism. If resume-first is ever viable it needs one, and that is
its own initiative.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`
- `phase-loop-runtime/src/phase_loop_runtime/lane_scheduler.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`

**Depends on**
- PROOFGATE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 7 — Leg Lifecycle and Board Extensibility (LEGLIFE)

**Objective**
Make board legs terminate, reap, and return an aggregate — then let a repo declare its own seats
and lenses now that lenses are real.

**Exit criteria**
- [ ] EC-LEGLIFE-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-LEGLIFE-1 — A leg exceeding its bound is killed and reported as a typed timeout, not silence; falsified by removing the enforcement, after which a leg runs past its cap
- [ ] EC-LEGLIFE-2 — The aggregate always returns, and no provider subprocess outlives it
- [ ] EC-LEGLIFE-3 — A supported single-leg entry point exists; documentation stops instructing operators to re-implement leg mechanics
- [ ] EC-LEGLIFE-4 — A repo can declare custom seats and lenses that reach the reviewer's prompt
- [ ] EC-LEGLIFE-5 — The gemini/agy seat receives equivalent material to repo-access seats, or the asymmetry is recorded in the verdict
- [ ] EC-LEGLIFE-6 — **Omnigent backing is REACHABLE from production.** A production surface (CLI flag or config → `OmnigentBacking.from_env`) constructs an `OmnigentBacking` and threads it into `invoke_board`, so an opt-in seat actually routes through Omnigent instead of degrading to `skip: backing 'omnigent' not served by homebrew`. Falsified by reverting to the `omnigent=None` default at `panel_invoker.py:3844`, after which the seat must skip. (Absorbed from v5 ABDOMNI — built, wired at `panel_invoker.py:4059`, unit-tested, and constructed by ZERO production callers.)
- [ ] EC-LEGLIFE-7 — **Board observability is REACHABLE from production.** A production `LedgerWriter` binds to the real state-ledger (not only the reference `JsonlLedgerWriter`), and the live entrypoint constructs an `AsyncForwardingSink` and passes `sink=` to `invoke_board`, so board runs actually emit envelopes. Falsified by dropping the `sink=` argument, after which `observer` is `None` at `panel_invoker.py:3941` and nothing is emitted. (Absorbed from v5 ABDOBS — same reachability gap.)

**Scope notes**
Two lanes: lane A owns timeout enforcement and child reaping; lane B owns the extensibility
surface and the per-repo seat declaration. Lane B is only meaningful once REVIEWTRUTH has made
`Seat.lens` load-bearing — before that, custom lenses would be fictional metadata.

**Non-goals**
Granting legs execution capability, and native-fill for TUI-policy seats.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`

**Depends on**
- REVIEWTRUTH

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 8 — Isolation and Verification Hardening (HARDEN)

**Objective**
Close the reachable security and verification gaps carried as open findings, starting with the one
that is exploitable rather than theoretical.

**Exit criteria**
- [ ] EC-HARDEN-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-HARDEN-1 — An absolute symlink cannot escape the staged review tree; falsified by restoring `copytree(symlinks=True)` without the containment check
- [ ] EC-HARDEN-2 — Path handling in the reconcile main loop is CWD-independent
- [ ] EC-HARDEN-3 — Goal-coverage enforce mode fails closed rather than passing vacuously when no EC-IDs are declared
- [ ] EC-HARDEN-4 — The login-shell interpreter shim resists the exotic bash-option and profile-introduced-version forms recorded in ah#241
- [ ] EC-HARDEN-5 — The fleet-wide review-leg isolation standard is either met or its residual is explicitly operator-accepted with a recorded rationale

**Scope notes**
Decompose into 2 lanes: lane A owns the staging/symlink containment (ah#259) and the isolation
standard (ah#248); lane B owns reconcile path handling, goal-coverage enforce mode, and the shim.
Lane A is the security-reachable work and should start first even though the phase is otherwise
parallel-safe.

**Non-goals**
Re-opening the accepted-residual register (ah#361). Items there are promoted individually only on
new reachability evidence.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`

**Depends on**
- (none)

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 9 — Broker, Train, and Channel Residuals (RESIDUAL)

**Objective**
Retire the accumulated verified-but-unscheduled defects in the broker, train, phase-loop, and
channel-provenance surfaces.

**Exit criteria**
- [ ] EC-RESIDUAL-0 — **TEST LANE LANDED FIRST.** This phase's tests were written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier that was RUN with its injection anchor asserted; and the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-RESIDUAL-1 — `publish_committed_branch` dedup keys include `base`, so a cross-base replay cannot skip the base scope-check
- [ ] EC-RESIDUAL-2 — A live-head-read failure on the pr_open resume path yields a typed blocker rather than an uncaught abort
- [ ] EC-RESIDUAL-3 — The null-oid merge-queue false-halt is closed for non-FAB repos, not only FAB-scoped nodes
- [ ] EC-RESIDUAL-4 — `phase-loop hotfix` refuses or correctly executes a `verification_command` containing shell operators; a false green is impossible
- [ ] EC-RESIDUAL-5 — An unbound channel session model is recorded and refused on mismatch, and no handoff or status surface reports it uncaveated
- [ ] EC-RESIDUAL-6 — A repair child cannot recursively launch repair, and an interruption cannot overwrite a trusted closeout
- [ ] EC-RESIDUAL-7 — The 28 deferred F841 findings are triaged and either fixed or individually justified

**Scope notes**
Decompose into 3 lanes over disjoint subsystems: lane A owns broker/train
(`verbs.py`, `train_runner.py`); lane B owns phase-loop CLI and repair
(`cli.py`, `runner.py`); lane C owns channel provenance (`launcher.py`, `handoff.py`) and the F841
triage. These share no interface freeze and may run fully concurrently.

**Non-goals**
The delta-review initiative (ah#191), which carries a `deferred` label and is not scheduled here.

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`

**Depends on**
- (none)

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 10 — Runtime Substrate (RUNTIME)

**Objective**
Deliver the non-broker runtime substrate absorbed from `convergence-v1` Phase 1: durable event
log, reconciliation against live state, adapter envelope conformance, and transcript-free
recovery. Its advisor-seat criterion is NOT here — it moved to REVIEWTRUTH.

**Exit criteria**
- [ ] EC-RUNTIME-0 — **TEST LANE LANDED FIRST.** Tests written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier RUN with its injection anchor asserted; the implementation PR does not modify them.
- [ ] EC-RUNTIME-1 — An append-only event log persists intent-before and outcome-after records per side-effect; falsified by dropping the intent record, after which a crash between intent and outcome is indistinguishable from no attempt
- [ ] EC-RUNTIME-2 — The reconciliation engine resolves live Git/GitHub/provider state rather than trusting cached state; falsified by stubbing the live read, which must then be detected
- [ ] EC-RUNTIME-3 — Codex, Claude, and at least one outside-agent adapter return the frozen envelope shape
- [ ] EC-RUNTIME-4 — `train-status` reconstructs train state from the ledger with no transcript available
- [ ] EC-RUNTIME-5 — The `convergence-v1` plan files (`plans/phase-plan-vergence-v1-RUNTIME.md`) are re-grounded against current main before execution, or explicitly superseded — they were authored 2026-07-13 and the runtime has moved considerably

**Scope notes**
Decompose into 3 lanes over disjoint files: lane A owns the event log, lane B the reconciliation
engine, lane C the adapter envelopes and `train-status`. Absorbed from `convergence-v1` Phase 1,
which carried a maintainer RESUME decision — treat its existing plan file as input, not as a
finished artifact.

**Non-goals**
The advisor-seat lifecycle (REVIEWTRUTH owns it). Broker admission (FABPUB).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/injection.py`

**Depends on**
- PROOFGATE

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `roadmap_amendment`; target surfaces:
`specs/**`, `plans/**`; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 11 — Coordinator Integration and Fault Suite (INTEG)

**Objective**
Absorbed from `convergence-v1` Phases 3 and 4: integrate the coordinator against the broker
substrate and prove it under adversarial faults. Merged because they share the same interface
freeze and would otherwise serialize needlessly.

**Exit criteria**
- [ ] EC-INTEG-0 — **TEST LANE LANDED FIRST.** Tests written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier RUN with its injection anchor asserted; the implementation PR does not modify them.
- [ ] EC-INTEG-1 — The coordinator drives side effects only through the broker; falsified by restoring any direct-credential path, which must be detected
- [ ] EC-INTEG-2 — Crash injection between broker admission and ledger append converges on resume rather than double-executing
- [ ] EC-INTEG-3 — The adversarial fault suite covers revocation mid-operation, ambiguous terminals, and concurrent same-target requests
- [ ] EC-INTEG-4 — `plans/phase-plan-vergence-v1-FAULTS.md` — hand-executed 2026-07-26 with 138 fault tests green — is reconciled into the ledger rather than left as bookkeeping-stale

**Scope notes**
Decompose into 2 lanes: lane A owns coordinator integration, lane B the fault suite. Absorbed
from `convergence-v1` INTEG + FAULTS. Note FAULTS was hand-executed outside the loop lifecycle —
its closeout was never recorded, which is the specific staleness EC-INTEG-4 closes.

**Non-goals**
Production pilots and release (RELEASE owns those).

**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`

**Depends on**
- FABREADMIT
- RUNTIME

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 12 — Pilots and Governed Release (RELEASE)

**Objective**
Absorbed from `convergence-v1` Phases 5 and 6: run parallel pilots on real trains, then the
governed production release.

**Exit criteria**
- [ ] EC-RELEASE-0 — **TEST LANE LANDED FIRST.** Tests written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier RUN with its injection anchor asserted; the implementation PR does not modify them.
- [ ] EC-RELEASE-1 — At least two parallel pilot trains complete with broker-mediated side effects and no direct-credential path
- [ ] EC-RELEASE-2 — Pilot evidence is machine-checkable, not prose asserting that a live run occurred; falsified by a test that string-matches a markdown evidence file, which must be rejected
- [ ] EC-RELEASE-3 — The release declares its production status honestly (`pilot-ready` / `deployed-not-baked` / `production-ready`) and does not overclaim
- [ ] EC-RELEASE-4 — Version bump, CHANGELOG, and RELEASE_PIN agree; the tag push that triggers OIDC publish remains user-gated

**Scope notes**
Two lanes: lane A owns the pilots, lane B the release mechanics. EC-RELEASE-2 exists because a
sibling repo's production-bake criteria are asserted in committed prose whose tests only
string-match the markdown — they pass whether or not the live run happened. Do not repeat that.

**Non-goals**
Publishing. Release dispatch is user-gated and stays that way.

**Key files**
- `phase-loop-runtime/pyproject.toml`
- `CHANGELOG.md`
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`

**Depends on**
- INTEG

**Produces**
- (none)

**Spec closeout policy**
schema: `spec_delta_closeout.v1`; expected decision: `no_spec_delta`; target surfaces: none
outside this repo; `redaction_posture: metadata_only`; malformed evidence routes non-human
`blocker_class=contract_bug`.

## Phase Dependency DAG

```
LEGIBLE ──────────────┐
                      │  (independent roots, all start immediately)
REVIEWTRUTH ──────────┼─────────────→ LEGLIFE
                      │
PROOFGATE ────────────┼─────────────→ SCHED
                      │
CONFORM ──────────────┤   [externally gated on spec#118 for EC-CONFORM-5/6]
                      │
FABPUB ───────────────┼─────────────→ FABREADMIT
                      │
HARDEN ───────────────┤
                      │
RESIDUAL ─────────────┘

Parallel roots (no shared ancestor):
  LEGIBLE ∥ REVIEWTRUTH ∥ PROOFGATE ∥ CONFORM ∥ FABPUB ∥ HARDEN ∥ RESIDUAL

Serial edges (only two in the whole roadmap):
  REVIEWTRUTH → LEGLIFE     (lens must be load-bearing before custom lenses mean anything)
  FABPUB      → FABREADMIT  (merge boundary enforces the mixed-allocation interlock)
  PROOFGATE   → SCHED       (SCHED's re-framed GC work should land under the falsifier gate)

Absorbed convergence-v1 chain:
  PROOFGATE → RUNTIME ─┐
  FABPUB → FABREADMIT ─┴→ INTEG → RELEASE

Critical path: PROOFGATE → FABPUB → FABREADMIT → INTEG → RELEASE
```

## External Dependencies (NOT phases — we do not own these)

| dependency | blocks | tracked |
|---|---|---|
| `Consiliency/spec` PR #102 ratify-or-supersede | EC-CONFORM-5, EC-CONFORM-6 | `spec#118` |
| `governed-pipeline` pin/version reconciliation | nothing here; informational | `governed-pipeline#128` |
| `consiliency-portal` outside-agent ingester (parked by decision) | nothing here | portal v51 |

Coordination happens through the four-repo outside-agent release train
(`governed-pipeline/specs/outside-agent-release-train-v1.md`), not through this roadmap.

## Execution Notes

Plan each phase with `/claude-plan-phase <ALIAS>`, then build with `/claude-execute-phase <alias>`.

Seven phases are independent roots and may be planned and executed concurrently:
**LEGIBLE, REVIEWTRUTH, PROOFGATE, CONFORM, FABPUB, HARDEN, RESIDUAL**.

Recommended start order when capacity is limited, and why:

1. **PROOFGATE and REVIEWTRUTH first.** Both REDUCE the cost of every later phase — one makes
   review verdicts trustworthy, the other makes proofs mechanical. Everything else consumes
   review capacity; these two increase it.
2. **LEGIBLE early**, because it is small and makes this roadmap's own progress reportable.
3. **FABPUB** whenever capacity allows; it is the critical path and independent of everything.
4. **SCHED** only after the ah#354 design fork is settled — lane B may proceed meanwhile.

Every review in this roadmap runs 3-of-4 until REVIEWTRUTH lands. Record the reviewing-seat count
with each verdict; do not report a 3-seat board as convergence.

## Verification

```bash
# Whole-suite regression, the gate every phase must leave green
PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"

# This roadmap parses and its DAG is acyclic
phase-loop validate-roadmap specs/phase-plans-v10.md

# LEGIBLE: every roadmap reports its own state without a ledger query
phase-loop worktree-index --help >/dev/null && echo "runtime present"

# REVIEWTRUTH: a board driven inside Harness Code cannot silently run 3-of-4
PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "advisor_board or governed_review"

# PROOFGATE: a falsifier-less acceptance item is rejected
PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "validate_plan or goal_coverage"

# CONFORM: the CANONICAL corpus passes through the real validator
PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "outside_agent"

# FABPUB/FABREADMIT: broker admission, fencing, and the readmit seam
PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests -q -k "broker or admission or convergence or fab"

# Lint gate (ah#334) — the guard that caught the F823 in ah#105
ruff check phase-loop-runtime/src/phase_loop_runtime/
```
