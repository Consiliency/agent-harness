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
(`panel_invoker.py:1065`, the leg-prompt renderer, whose signature omits lens) — while ratification counts it as coverage
(`ratification_policy.py:174`). One seat returned AGREE on four consecutive reviews while
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

1. ~~`Consiliency/spec` PR #102 remains unmerged; our contract pin (`c1085483`) is therefore
   unsatisfiable from merged sources. CONFORM's pin work is externally gated (`spec#118`).~~
   **STALE — invalidated 2026-07-29 by this repo's own merges while v10 was in review** (a new
   class: a fail-loud assumption that went wrong WITHOUT failing loud). `spec#102` MERGED
   (2026-07-29), the ratification-review gate `spec#118` is CLOSED, and `agent-harness#377` landed
   the `v0.2.1` pin on `main` — `outside_agent_pin.py` now records `contract_git_tag="v0.2.1"`,
   `contract_git_sha="b862f977…"` (superseding `c1085483`) plus per-schema `submission_schema_sha256`
   / `verdict_schema_sha256`. CONFORM's pin work is therefore NO LONGER externally gated and is
   satisfiable against merged sources; EC-CONFORM-5/6/7 are re-derived accordingly below. (Swept
   the other four assumptions against current `main`: #2 re-verified LIVE — `governed-pipeline#128`
   still OPEN, we still ship `0.7.13`; #3 holds — `tui_adapter_required` still present in
   `panel_invoker.py`, REVIEWTRUTH unlanded; #4/#5 structurally independent of #377. Only #1 went
   stale.)
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
- **IF-0-REVIEWTRUTH-1** — the typed per-seat outcome (`reviewed | unavailable | errored | timed_out`)
  carried on `PanelLegResult`, distinct from its `text` payload, plus the reviewed-seat count exposed
  to ratification. REVIEWTRUTH lane A DECLARES this shape — including the `timed_out` variant (the
  typed `leg_timeout`) — at the freeze on day 1; LEGLIFE lane A IMPLEMENTS the enforcement that
  produces a `timed_out` leg (kill-on-bound + typed report). `EC-REVIEWTRUTH-7`'s retry-not-count
  routing is validated against this FROZEN variant (a synthesized `leg_timeout`), and `EC-LEGLIFE-1`
  is validated by requiring the enforcement to emit THIS variant and no other — so both sides depend
  on the frozen contract, not on each other. Publishing the timeout variant in this REVIEWTRUTH-owned
  freeze, before either implementation, is what dissolves the criterion-level LEGLIFE→REVIEWTRUTH
  edge a phase-granularity DAG cannot see.
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
supersession banner pointing here; where a phase was already delivered it is recorded as such
rather than re-scheduled.

> **This table's first draft asserted "Nothing was dropped." That was false, and a cross-vendor
> review caught three drops before merge.** (1) `convergence-v1`'s process-boundary credential
> isolation (`:291`) vanished into an `EC-INTEG-1` that only requires calls to traverse a broker
> *abstraction* — which passes today while workers can still hold `GH_TOKEN`; restored as
> `EC-INTEG-5`. (2) `convergence-v1:340`'s production-wiring obligations for
> `reconcile_before_action` / `dispatch_ready_nodes` / `refresh_downstream_after_merge`, all three
> of which have zero production callers; restored as `EC-INTEG-6`. (3) `phase-plans-v4.md` was
> marked DELIVERED — CLOSED with "nothing carried" while its PNLVERIFY real-panel smoke had never
> been satisfied; carried as `EC-REVIEWTRUTH-9`.
>
> All three are the **MERGED IS NOT REACHABLE** class this roadmap's own Context section names —
> reproduced by the absorption pass itself. Writing the pattern down did not prevent committing
> it. Treat any "nothing was dropped" claim, including this one, as a hypothesis to be checked
> against the superseded document rather than as a finding.

| absorbed roadmap | disposition | where its live work went |
|---|---|---|
| `phase-plans-convergence-v1.md` | SUPERSEDED (had maintainer RESUME 2026-07-26) | FREEZE→LEGIBLE (the #312 status contradiction); RUNTIME→RUNTIME + REVIEWTRUTH (its advisor-seat criterion); BROKER→FABPUB/FABREADMIT; INTEG/FAULTS/PILOT/RELEASE carried forward as phases |
| `phase-plans-v7.md` (Outside-Agent Conformance) | SUPERSEDED | OAMOCK delivered (no carry); OACORE-3 + OAREAL-2 → CONFORM; OACONTRACT + OARELEASE → CONFORM, ~~externally gated on `spec#118`~~ **gate CLEARED 2026-07-29** (`spec#102` merged, `spec#118` closed, `agent-harness#377` landed the `v0.2.1` pin) |
| `phase-plans-v6.md` | **DELIVERED — closed, not absorbed** | Nothing carried: all 5 phases shipped (#114 via #115/#116/#118, 27 tests green). Closed with a DELIVERED banner, a distinct disposition from superseded. |
| `phase-plans-v1.md` | **DELIVERED — closed** | Nothing carried; 7 phases shipped via #3, released v0.1.4 |
| `phase-plans-v1-task-message-sourcebroker.md` | **DELIVERED — closed** | Nothing carried; shipped `bf7d5e0` (#168) + hardening #176–#190 |
| `phase-plans-cross-repo-v1.md` | **DELIVERED — closed** | Nothing carried; 5 phases shipped `5423486` (#35/#29). Its MVP non-goals (parallel DAG-of-DAGs, auto-revert, content-hash identity) are FUTURE scope, deliberately not carried |
| `north-star-pi-native.md` | **RETAINED — not a roadmap, not closed** | Vision + gated backlog; authorizes nothing. Its 4 principles folded into this roadmap's Cross-Cutting Principles (8–11); its 6 backlog gates stay there as candidates |
| `phase-plans-v9.md` | **SUPERSEDED — ABSORBED** | 4 of 5 phases DELIVERED (#238/#243/#231, #244/#245, #250, #91). ONE live phase: FAB agent-harness#191 delta review, dormant because `_FAB_DELTA_BROKER_READMIT_READY=False`. Carried into FABREADMIT as EC-FABREADMIT-6/7. FAB **lane (a)**, v9's worktree-loss prerequisite (`v9:357`) that v9 left "CANNOT-DETERMINE, not carried" (`v9:16`), is NOT dropped — superseding v9 makes its acceptance condition our responsibility, carried as **EC-SCHED-7** with a recorded disposition (both branches survive on `origin`; the four worktrees are gone; uncommitted deltas explicitly discarded) |
| `phase-plans-v8.md` | **DELIVERED — closed** | Nothing carried; EXECREG/GROKEXEC/AUTOSEL/DISSECT all shipped (#144/#148/#150/#152/#142) |
| `phase-plans-v3.md` (model-routing-v2) | **SUPERSEDED — ABSORBED** | 2 of 4 phases DELIVERED (P2 real panel spawn, P3 planning gate). P1 (live pre-merge gate) AND P4 (`v3:191` end-to-end invariants) BOTH require the production block→fix→pass round, unwired (`runner.py:10140` `apply_fix=None`) — a fourth delivered-but-unmet; carried by EC-REVIEWTRUTH-8, which now carries both obligations |
| `phase-plans-v2.md` (model-routing-v1) | **SUPERSEDED — ABSORBED** | Re-derived from `#309`/`#310` commits (NOT the banner): 3 of 5 phases fully DELIVERED (P1 resolver-live, P2 planning gate live `runner.py:2328`, P5 invariants+docs), TWO delivered-but-unmet. P3 shares v3's production fix-round gap (`apply_fix=None` at `runner.py:10140`) → EC-REVIEWTRUTH-8. **P4 (Route Logging & Observability) exit-crit 2 (`v2:207`) is a FIFTH delivered-but-unmet** — governed panel verdicts are never emitted to the run-end summary (`panel_verdict_record` has ZERO production callers; a passing governed run's summary shows no evidence a panel reviewed the merge) → EC-REVIEWTRUTH-10. The earlier "unverified at phase level" caveat is now RESOLVED into that carried criterion. P4 crit 1 (route logging) IS met (`with_route_log`, `runner.py:6080`). Honest limit: P1 crit 4's migrated baseline assertions were confirmed seam-live but not independently re-run. Shipped effort defaults (`execute/repair=high`, `review=max`) intentionally differ from the doc under #310 — a reconciliation, not a delivery gap |
| `phase-plans-v5.md` (Advisor Board) | **SUPERSEDED — ABSORBED** | Phases 1–4 and 7 DELIVERED. ABDOMNI + ABDOBS are built, wired and unit-tested but have ZERO production constructors → EC-LEGLIFE-6/7. The `<harness>-advisor-panel` bundle dirs are an INTENDED, test-enforced compat alias (`install_skills`/`SKILL_ALIASES`, byte-identical to `advisor-board` modulo `name:`, asserted by `test_advisor_board_alias_install.py`), NOT a stray — `v5:153` clause 3's pre-rename divergent duplicate is removed; nothing carried |
| `phase-plans-v4.md` (Advisor Panel ownership) | **SUPERSEDED — ABSORBED** | 5 of 6 phases shipped `9de824d`/`61f41c6`, focused slice 46/0 today. Three deliberate supersessions recorded in its banner (fable-5 leg default, gemini-3.6-flash, panel→board rename) so they are not mistaken for regressions. **CARRIES ONE LIVE CRITERION:** PNLVERIFY's real-panel smoke (`phase-plans-v4.md:246`) was never satisfied — its own execution plan permitted the smoke not to run (`plans/phase-plan-v4-PNLVERIFY.md:52`) and the committed closeout records no live model-output transcript, substituting command-construction tests (`docs/research/advisor-panel-roadmap-v4-verification.md:44`) → EC-REVIEWTRUTH-9 |

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
- [ ] EC-LEGIBLE-2 — `select_roadmap`'s chosen roadmap is identifiable from the repo without executing it; falsified by removing the on-disk selection marker and finding the chosen roadmap resolvable only by running `select_roadmap` — the observable is the selected roadmap path readable from the repo, not computed at runtime
- [ ] EC-LEGIBLE-3 — A plan file present on disk but absent from `plans/manifest.json` is reported by a check, not silently invisible to discovery; falsified by adding an on-disk plan file absent from the manifest and finding the check stays green — the observable is the check naming the unregistered file (a non-empty list/count), not silence
- [ ] EC-LEGIBLE-4 — agent-harness#347 is merged, its PR body citing only commits present in its head's ancestry; falsified by a cited commit SHA that `git merge-base --is-ancestor <sha> <head>` rejects — the observable is a non-ancestor SHA appearing in the PR body
- [ ] EC-LEGIBLE-5 — The `.claude/docs-catalog.json` scaffold either gains its rescan implementation or is removed; an empty catalog no longer reads as a populated one; falsified by leaving an empty `.claude/docs-catalog.json` in place and finding a reader still reports it populated — the observable is the reported catalog entry count read as >0 while the file enumerates none. (Disposition on the "or is removed" arm, verified against round-7 finding 5: this is a LEGIBILITY criterion — empty ≠ populated — and deletion is a legitimate resolution because a deleted scaffold cannot lie; it is NOT a carrier for `agent-harness#367`, a SEPARATE and UNRATIFIED decision about cataloging CLIENT-owned documents whose forks D1a-scan/D1b-declare are still open. v10 claims nowhere to deliver #367, so EC-LEGIBLE-5 does not DROP it — but because #367 names this exact scaffold as "closest to the intent," the removal arm must NOT be exercised while #367 is open and unresolved: deleting the scaffold here does not resolve #367, and if #367 later ratifies populating it, removal is off the table.)
- [ ] EC-LEGIBLE-6 — **THE "ASSUMPTIONS (FAIL-LOUD IF WRONG)" BLOCK MUST ACTUALLY FAIL LOUD WHEN AN ASSUMPTION GOES STALE — no mechanism delivers this today (obligation-derived; sibling of EC-LEGIBLE-3's self-reported-drift shape, the phase objective being a roadmap that reports its own state — and this block reports none of its own).** The obligation is mechanism-AGNOSTIC: a stale assumption — one whose current live state contradicts what the assumption asserts — is DETECTED and fails loud by ANY means; the 5 assumptions carry machine-checkable references (`spec#102`, `governed-pipeline#128`, `v0.2.1`/`b862f977…`, `#170`, `ah#363`), but resolving those against a GitHub API is ONE possible mechanism, NOT the definition (#3/#5 do not resolve by the same call as #1/#2, so the criterion must not inherit that mechanism's coverage gaps). Falsified TODAY — operative, keyed on a MUTATION so it fires against the CURRENT doc and not on any already-remediated clause — by mutating any assumption to assert a fact its live state contradicts (e.g. flip #2 to claim `governed-pipeline#128` is CLOSED while it is open) and observing NO check flags it. Two-arm, so an always-fail audit cannot satisfy it: (a) that mutated assumption is flagged stale, AND (b) an UNMUTATED live assumption (#2 as written — `governed-pipeline#128` open, still shipping `0.7.13`) is NOT flagged. Motivation (historical, already materialized — explicitly NOT the falsifier): Assumption 1 sat asserting `spec#102` unmerged / `c1085483` pinned for ~4 hours AFTER `agent-harness#377` invalidated both facts with nothing failing loud, so the risk is demonstrated, not hypothetical (the "vacuous on a timer" form). NO mechanism exists today — same honest state as EC-INTEG-5/-6.
- [ ] EC-LEGIBLE-7 — **DISCOVERY DOES NOT RESOLVE A ROADMAP WHOSE OWN BANNER MARKS IT SUPERSEDED / DO-NOT-EXECUTE — no mechanism delivers this today (obligation-derived; this is the consolidation's HEADLINE claim — "one active roadmap" — made BEHAVIOURALLY, and a resolver that selects a superseded roadmap falsifies it; sibling of EC-LEGIBLE-6 one step out: self-reported state that a BEHAVIOURAL surface, not prose, contradicts).** The obligation is mechanism-AGNOSTIC: the roadmap resolver does not return a roadmap marked superseded/do-not-execute. Falsified TODAY by `active_state_roadmap` (`discovery.py:445`) reading `.phase-loop/state.json`, whose `roadmap` field points at `specs/phase-plans-convergence-v1.md` — a do-not-execute roadmap — and by `manifest_backed_roadmap` (`discovery.py:467`) reading `plans/manifest.json` where convergence-v1 is present and **v10 is unregistered**; the observable is the resolved path being a superseded roadmap. Two-arm, so an always-return-`None` resolver cannot satisfy it: (a) a resolver returning a do-not-execute roadmap FAILS, AND (b) a resolver returning a genuinely-active non-superseded roadmap PASSES (returning `None` on an all-superseded set is acceptable — the degenerate "select nothing" does not count as satisfying "never selects a superseded one"). NO mechanism exists today, and the fix is NOT a docs edit: the state marker and manifest still select convergence-v1, v10 is itself ABSENT from `plans/manifest.json` (its OWN EC-LEGIBLE-3 check would flag the active roadmap as unregistered), and repointing is a BEHAVIOUR change a DOCS-ONLY / PLAN-ONLY PR must not make unilaterally — it needs `state.json`→v10 AND marking convergence-v1 completed/superseded in the manifest (because `manifest_backed_roadmap` returns `None` when >1 candidate, so naively adding v10 alongside a live convergence-v1 BREAKS discovery). This is the behavioural surface the v7 banner already calls "a bookkeeping defect" while nothing in the consolidation fixes it — same honest state as EC-INTEG-5/-6, a required maintainer-gated follow-up, not a silently-claimed delivery.

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
- [ ] EC-REVIEWTRUTH-1 — A governed board classifies its seat count into one of THREE distinct states — FULL (delivered reviewing seats == target, `DEFAULT_TARGET_SEATS=4` at `composition.py:66`), FLOOR-ONLY (floor ≤ delivered < target, `FLOOR_SEATS=3` at `composition.py:67`), or BELOW-FLOOR (delivered < floor) — where a FLOOR-ONLY board carries a typed shortfall signal to the caller and can NEVER be reported as FULL convergence, and a BELOW-FLOOR board cannot report convergence at all. The motivating incident was AT floor, not below it: with the claude seat structurally unfillable, 3-of-target-4 sits at FLOOR and previously converged with `native_fill_requests: 0` and no signal to the caller (ah#358 — the floor is enforced on the CLI path at `cli.py:1533` but the governed pre-merge path does not dispatch it). Falsified by re-running the three 2026-07-28 governed boards and finding any reports convergence with NO FLOOR-ONLY/shortfall signal reaching the caller — the observable is a governed at-floor board indistinguishable from a full 4-seat board in what the caller receives (this arm FIRES on the incident, whereas the prior "must still be blocked" arm could not: those boards were never blocked, they converged, so a falsifier asserting they were blocked could never fire on the very incident it cited). Positive control: a genuine 4-of-4 board is classified FULL with no shortfall, and a 2-of-4 board is BELOW-FLOOR and cannot converge
- [ ] EC-REVIEWTRUTH-2 — An unusable leg is distinguished from a reviewing leg WITHOUT inspecting `text`; falsified by reverting to the `text.strip()` predicate
- [ ] EC-REVIEWTRUTH-3 — A spawn that RAISES does not produce a governed BLOCK from its traceback; falsified by a leg spawn raising and its traceback text being emitted as a governed BLOCK finding — the observable is a BLOCK whose body is the exception traceback. Positive control: a spawn that genuinely reviews and blocks still yields a real BLOCK, proving the raise-path is what is suppressed, not all blocks
- [ ] EC-REVIEWTRUTH-4 — A board driven inside Harness Code resolves to one of the SAME three states as EC-REVIEWTRUTH-1 — FULL (4 reviewing seats), FLOOR-ONLY (3 reviewing seats paired with a typed unfillable signal, which MAY proceed but is NOT reported as FULL convergence), or BELOW-FLOOR (blocked); a silent 3-of-4 reported as FULL is impossible. This dissolves the prior conflict with EC-REVIEWTRUTH-1: a typed 3-seat outcome is legitimately allowed to PROCEED, but classified FLOOR-ONLY, never as FULL convergence — the two criteria now share one three-state vocabulary, so "below-floor cannot converge" (`-1`) and "a typed 3-seat may proceed" (`-4`) no longer contradict. Falsified by forcing one seat unfillable and finding the board reports 4-of-4 (FULL) convergence or an untyped fill — the observable is the reviewed-seat count (3) paired with the typed unfillable signal classified FLOOR-ONLY, never a silent FULL 4. Positive control: a board with all 4 seats filled is classified FULL, proving FLOOR-ONLY is specifically the at-floor 3-seat case and not the default
- [ ] EC-REVIEWTRUTH-5 — `Seat.lens` reaches the reviewer's prompt, and ratification counts lens coverage only for seats whose prompt carried it; falsified by blanking the lens before prompt assembly and finding (a) the reviewer prompt unchanged and (b) ratification still crediting lens coverage — the observable is the lens string present in the rendered prompt AND the coverage tally dropping to zero when it is absent
- [ ] EC-REVIEWTRUTH-6 — `test_advisor_board_golden.py` still passes, or its sanctioned-delta list is explicitly and normatively amended; falsified by a golden-output change landing with neither a green `test_advisor_board_golden.py` nor a recorded sanctioned-delta amendment — the observable is a golden diff unaccounted for by the delta list
- [ ] EC-REVIEWTRUTH-7 — A capped, empty, or TIMED-OUT leg is distinguishable from a leg that reviewed and found nothing, and is retried rather than counted; falsified by feeding an empty (capped) leg result OR a typed `leg_timeout` result and finding it counted as a reviewing seat rather than retried — the observable is the leg's typed status (capped/empty/timed-out) driving a retry, not a seat increment. The typed `leg_timeout` variant is DECLARED in `IF-0-REVIEWTRUTH-1` (REVIEWTRUTH lane A's day-1 freeze of the per-seat outcome), and the leg-killing ENFORCEMENT that produces it originates in LEGLIFE lane A (`EC-LEGLIFE-1`: "a leg exceeding its bound is killed and reported as a typed timeout"); a `timed_out` leg MUST reach this retry-not-count path — a timed-out leg that buckets "unusable" but is never retried is the cross-phase seam this closes, since `-7`'s prior "capped or empty" wording most likely excluded "timed out". Positive control: a leg that genuinely reviewed and returned no findings IS counted, not retried, proving the two are distinguished. THIS lane's VALIDATION consumes only the FROZEN `timed_out` variant (a synthesized `leg_timeout` result), NOT LEGLIFE lane A's runtime output; LEGLIFE lane A owns timeout enforcement and child reaping (per LEGLIFE's Scope notes — the earlier "lane B" attribution was WRONG; lane B owns the extensibility surface / per-repo seat declaration). **CROSS-PHASE CYCLE — RESOLVED VIA INTERFACE FREEZE (not narrowed, not reordered):** EC-7 once appeared to CONSUME LEGLIFE lane A's `leg_timeout` — a LEGLIFE→REVIEWTRUTH content edge — while the phase DAG draws REVIEWTRUTH→LEGLIFE (LEGLIFE lane B's custom-seat/lens work depends on REVIEWTRUTH making `Seat.lens` load-bearing). Freezing the `timed_out` variant in `IF-0-REVIEWTRUTH-1` (published day 1, before either implementation) cuts that back-edge: EC-7 validates against the frozen type and LEGLIFE lane A (`EC-LEGLIFE-1`, tightened to require THIS variant) implements enforcement against the same frozen type, so both sides depend on the contract, not on each other — acyclic at LANE granularity (LEGLIFE lane A → freeze ← REVIEWTRUTH EC-7; then REVIEWTRUTH → LEGLIFE lane B) and no longer only at phase granularity. A residual gap is SEPARATELY TRACKED, not minted here: the roadmap validator checks PHASE edges not CRITERION content, so it could not have seen the original criterion-level cycle at all — filed as `agent-harness#385` against the validator (its recommendation: make cross-phase criterion references UNREPRESENTABLE by requiring an interface freeze — the route taken here — rather than regex-scan criterion prose, which is the wrong instrument for a semantic question; and mutation-test the resulting gate against this exact REVIEWTRUTH↔LEGLIFE instance), a linter concern that belongs against the validator, not as a criterion inside the document the validator checks
- [ ] EC-REVIEWTRUTH-8 — **The governed pre-merge auto-repair fix-round is WIRED IN PRODUCTION.** Build an `apply_fix` closure reusing `_build_repair_context` (`runner.py:6931`) + `build_prompt` + `launch_with_spec` to re-dispatch `repair` with the panel's `block` findings folded into `repair_context`, re-render the bundle from the new staged diff, and pass it — not `None` — at `runner.py:10140`. This carries BOTH v3 obligations: **P1** (`v3` Phase 1 exit-crit 3) — the `apply_fix` closure is built (from `_build_repair_context`, `runner.py:6931`) and passed — not `None` — at `runner.py:10140`, and a governed run with a mock panel returning block-then-pass shows the fix re-dispatched then the phase mergeable; AND **P4** (`v3:191` Phase 4 exit-crit 1) — an END-TO-END governed run (plan-gate → execute → pre-merge review → fix round → mergeable, plus the non-convergence terminal, serial path) drives the fix round through the PRODUCTION `apply_fix` at `runner.py:10140`, not a test-injected closure. Falsified by (a) reverting to `apply_fix=None`, after which the mock-panel block-then-pass run must NOT become mergeable; OR (b) the end-to-end test passing while `runner.py:10140` still supplies `None` or the mergeability traces to a test-injected closure rather than the production call site — the observable is the E2E path becoming mergeable without the production `apply_fix` firing. Positive control: the phase becomes mergeable within `max_rounds` (default 3) via the production closure, with the governed fix-round counter kept independent of `_recent_repeated_repair_failures`. (Absorbed from v3 P1 AND P4 / v2 P3 — both v3 phases require the production fix-round, so v3 is a fourth delivered-but-unmet, not a single-phase gap; the loop machinery exists at `governed_premerge.py:371-373` and is exercised only by test-injected closures; `runner.py:10140` passes `apply_fix=None`, deliberate and self-documented at `runner.py:9748-9757`.)
- [ ] EC-REVIEWTRUTH-9 — **REAL-PANEL SMOKE, carried from v4 PNLVERIFY (`phase-plans-v4.md:246`), which was closed without satisfying it.** This is v4's SOLE PNLVERIFY real-panel-smoke exit criterion — a live panel proving the legs can INSPECT the staged files — NOT the only smoke obligation in v4, so it must not be read as "the sole smoke exit criterion": a SEPARATE v4 obligation (`v4:217` PNLREDACT / `v4:279` acceptance) requires the legs to RECEIVE compact prompts that POINT at staged review files, not embedded bodies or implicit directory reads. That upstream compact-prompt obligation is MET and carried in behavior, so it is deliberately NOT given its own criterion (a falsifier against it could not fire): `_render_leg_prompt` (`panel_invoker.py:1065`) renders a compact prompt naming `instructions_path`/`bundle_path` and explicitly does NOT paste the bundle body ("intentionally staged as a Markdown file instead of being pasted into the initial prompt"), the dotfiles path was redacted to a delegating compatibility shim (dotfiles `advisor-panel/SKILL.md` now calls `phase_loop_runtime.panel_invoker.invoke_panel`; the standalone `run_cli_panels.sh` is removed), and construction+argv are golden-tested (`launchspec_golden.json`) — that golden IS the `v4:217` "reproducer or smoke test", closing its proof half. THIS criterion is therefore scoped strictly to INSPECTION (did the leg open the pointed-at files), the downstream and still-UNMET half. A live panel run produces a durable transcript proving the Codex and Gemini legs actually inspected the staged files — not that their commands were constructed correctly. v4's own execution plan permitted the smoke not to run (`plans/phase-plan-v4-PNLVERIFY.md:52`) and its closeout substituted command-construction tests with no live model output recorded (`docs/research/advisor-panel-roadmap-v4-verification.md:44`). Falsified by a leg that returns a verdict while self-disclosing it opened no files — the same non-corroborating-AGREE failure observed on `#368` round 1, where a seat agreed having read no source. Positive control: the transcript names files the leg could only know by reading them
- [ ] EC-REVIEWTRUTH-10 — **GOVERNED PANEL VERDICTS ARE EMITTED BY THE PRODUCTION GATES AND SURFACED IN THE RUN-END SUMMARY (restored from v2 Phase 4 exit-crit 2, `phase-plans-v2.md:207` — "Panel verdicts and any degraded/advisory-warn flag are recorded and surfaced through the … run-end summary … a governed-run summary names the panel outcome"). A MERGED-IS-NOT-REACHABLE instance — mechanism built, exported, unit-tested, ZERO production callers (`review_summary.panel_verdict_record`, the sole producer of `kind:"panel_verdict"` at `review_summary.py:94`, is constructed nowhere in `src/`; `panel_verdict` occurs in `src/` only inside `review_summary.py`) — the same shape as `apply_fix=None` (EC-REVIEWTRUTH-8) and `_FAB_DELTA_BROKER_READMIT_READY=False`; first found by a commit-level walk of `#309`/`#310`, not by reading code against intent.** The obligation: `_governed_premerge_review` (`runner.py:10103`) and `_governed_planning_gate` (`runner.py:9802`) must emit a `panel_verdict` record on EVERY governed outcome — mergeable, blocked, AND degraded/advisory-promote — so `summarize_run` (`runner.py:10250`) names the verdict and the degraded/advisory-warn flag. Today the pre-merge PASS path `return None`s and emits nothing, the block path writes only `governed_premerge` metadata, and `_governed_planning_gate` returns `None` on promote INCLUDING the degraded-advisory case — none carry `kind:"panel_verdict"`, so `collect_panel_verdicts` returns `[]` on every real governed run. Falsified by (a) a REAL governed closeout after which `collect_panel_verdicts(events) == []` — the observable is the empty panel-verdict block in the live run's summary, NOT the presence of `panel_verdict_record` in the module; and (b) a single-authed-vendor governed run whose run-end summary does not name the advisory-warn degradation (the arm `v2:207` names explicitly and `_governed_planning_gate`'s degraded-promote path most easily drops). NOT satisfiable by a test that INJECTS a `panel_verdict` record into hand-built events — `test_panel_verdict_summary.py` does exactly that today (`panel_verdict_record(...)` planted into `{"metadata": {"panel": …}}`); the test must drive the production gate through a governed run. Positive control: a PASSING governed pre-merge review still records a `mergeable` verdict, proving emission is not block-only. (Distinct from the fix-round EC-REVIEWTRUTH-8 carries; individual `block`/`nit` findings ALREADY surface via the review-findings block because `ReviewFinding.to_json()` carries `kind:"review_finding"` — only the verdict and degraded flag are missing, so this is scoped to verdict emission, not findings.)
- [ ] EC-REVIEWTRUTH-11 — **ADVISOR-SEAT LIFECYCLE IS PERSISTED AS DURABLE PER-SEAT OUTCOMES ON THE LIVE (NON-FAB) GOVERNED BOARD PATH (restored from `convergence-v1` RUNTIME exit-crit 4, `phase-plans-convergence-v1.md:256-257` — "Advisor-seat lifecycle persists complete per-seat outcomes (required/optional, timeout, degraded) into the event log"; the RUNTIME SEATS lane names `panel_invoker.py` seat-lifecycle + persistence at `convergence-v1:263-264` and Key files `convergence-v1:275`).** A MERGED-IS-NOT-REACHABLE instance — the mechanism is built and typed (`SeatOutcomeRecord` carries `required` at `panel_invoker.py:514` and `status` at `:515`; `persist_seat_outcome` at `panel_invoker.py:557` serializes and appends it) but has NO PRODUCTION DESTINATION ON THE LIVE PATH: `persist_seat_outcome` takes an injectable `append_sink: Callable[[str], None]` that NOTHING injects (zero callers in `src/` — only its def plus two doc-comments in `fab_gate.py`), and the sole production writer of the serialized format is FAB's own `append_seat_outcome` (`panel_invoker.py:533` docstring), invoked only at `fab_producer.py:260,397` — the DORMANT `_FAB_DELTA_BROKER_READMIT_READY=False` path, which no board in this repo runs today; even the in-memory capture (`fab_producer.capture_review_at_invocation`, `runner.py:10119-10124`) is reached ONLY when `fab_run_id` is set, so the non-FAB path (`fab_run_id=None`, every board today) captures nothing, byte-neutral by design. **The SEVENTH instance of this class (`panel_verdict_record`/EC-REVIEWTRUTH-10 was the sixth) — the same shape as `apply_fix=None` (EC-REVIEWTRUTH-8), `_FAB_DELTA_BROKER_READMIT_READY=False`, and ABDOMNI/ABDOBS (EC-LEGLIFE-6/7): an injectable sink nobody injects, found this round by chasing the obligation against the wiring; if it has its own falsifier it is its own criterion.** The obligation: a real NON-FAB governed board must persist one durable `SeatOutcomeRecord` per seat (its `required`/optional flag, and its `status` including timeout and degraded) into a coordinator ledger, so the per-seat lifecycle is reconstructable from the event log ALONE (the RUNTIME recovery invariant), not only in memory for the run's duration. Falsified by (a) running a REAL non-FAB governed board after which no durable per-seat records reconstruct each seat's `required`/`status` from the event log — the observable is the absent per-seat lifecycle in the ledger after a live governed board, MECHANISM-AGNOSTIC (any production writer satisfies it — the point is persistence, not a specific symbol firing), NOT the presence or absence of the `persist_seat_outcome`/`SeatOutcomeRecord` symbols; or (b) a governed board with a seat that TIMED OUT or ran DEGRADED whose durable ledger cannot distinguish it from a seat that reviewed and passed — the observable is the missing or uniform `status` on the persisted record. NOT satisfiable by the FAB `append_seat_outcome` path (dormant) nor by a test that hands `persist_seat_outcome` a hand-built sink — the sink must be the production coordinator ledger wired into the live governed board. Positive control: a governed board with N seats writes N durable records whose `required` + `status` reconstruct each seat's lifecycle from the ledger with no transcript present. (Distinct from EC-REVIEWTRUTH-10, whose observable is `collect_panel_verdicts(events) == []` at the run-END SUMMARY level; this is PER-SEAT lifecycle persistence into the ledger — the seat-by-seat record, not the aggregate verdict.)
- [ ] EC-REVIEWTRUTH-12 — **RUNTIME GROUNDING/VETO — the board does not COUNT an ungrounded verdict, and encodes a distinct REFUSED state (ratified 2026-07-29 on the empirical record that a lone grounded codex DISAGREE was right on four boards a fail-open majority would have passed — a fail-open, a crash path, a leak channel, and a safety criterion satisfiable by documenting its own failure).** Three observables the current model lacks: (1) an AGREE that is NOT GROUNDED IN THE ARTIFACT — it surfaces NO evidence derivable only from the staged bytes (no quoted line, no path+line, no detail unique to the artifact) AND/OR self-discloses non-inspection (ran no commands, opened no files) — must NOT count toward convergence; today `PanelLegResult.usable = (status=="OK" and text.strip())` (`panel_invoker.py`) scores it identically to a grounded seat, so a seat that reviewed nothing and said so is a vote. GROUNDING is the DEFINITION here; an artifact-derived `file:line` anchor count is a HAND-PROXY for grounding, NOT the criterion — a conforming implementation keys on whether the verdict is grounded in the artifact by ANY mechanism, so the criterion does not inherit any single regex's blind spots (e.g. a proxy pattern like `[a-z_]+\.(?:py|md):\d+` that misses hyphenated or digit-bearing filenames must never become the definition, or the seat that IS grounded gets mis-scored ungrounded); (2) a leg that reviewed the REPO instead of the staged artifact must SAY SO, so silent compensation cannot mask a defective bundle from the other seats; (3) a leg that detects an artifact/SHA mismatch and refuses is recorded as a distinct REFUSED state — separate from "reviewed and found nothing" and from "unavailable" — a state that does not exist in the model at all today. Falsified (the falsifier ALREADY FIRED in production) by handing the board an empty diff under a SHA whose commit carries content and finding MORE THAN ONE usable seat: on ah#368 round 9 (2026-07-29) an empty-diff bundle staged under a 1,774-line-addition SHA yielded gemini AGREE / 0 anchors / self-disclosed non-inspection + grok AGREE / 12 real `file:line` anchors / silent repo-compensation + codex REFUSED, ratifying 2–1 against a blank artifact across 9 rounds and 29 findings. Positive control (two arms, so a degenerate count-nothing veto cannot pass): (a) that empty-diff-under-content-SHA input yields EXACTLY ONE usable seat — gemini's ungrounded AGREE excluded and codex recorded REFUSED, never two AGREEs plus a refusal scored as a lone DISAGREE; AND (b) that one usable seat IS grok's GROUNDED read, which STILL COUNTS — an implementation that reaches "at most one" by refusing to count grok's grounded AGREE too (or by never counting any AGREE at all) FAILS this control, proving the rule excludes UNGROUNDED verdicts selectively, not all verdicts (the verdict-layer analog of EC-REVIEWTRUTH-13's material-layer "non-empty substantive artifact still PASSES" arm: ungrounded ⇒ not counted, grounded ⇒ still counts). (Distinct from EC-REVIEWTRUTH-9, whose observable is a proving smoke TRANSCRIPT that a leg opened files; this is the RUNTIME refusing to COUNT an ungrounded verdict at convergence time — the untyped ungrounded-AGREE that EC-REVIEWTRUTH-2 and EC-REVIEWTRUTH-7 do NOT cover, since those close only the TYPED unavailable/capped/empty/timed-out cases while this closes the untyped case with no non-text signal at all.)
- [ ] EC-REVIEWTRUTH-13 — **THE GOVERNED GATE FAILS CLOSED ON EMPTY OR ELIDED REVIEW MATERIAL — INDEPENDENT OF LEG VERDICTS AND INDEPENDENT OF THE FAB FLAG (SOLE carrier; no FAB criterion asserts this ungated non-FAB guard — EC-CONFORM-8 is the sibling precedent, not an overlap).** The substance-completeness predicate ALREADY EXISTS and is correct — `_diff_text_elision`/`_numstat_binary_elision` keyed on `_DIFF_ELISION_SENTINELS` (`fab_producer.py:94,133,146`) encode "empty or elided material ⇒ the reviewer did not see the bytes ⇒ fail closed" — but it is QUARANTINED: those three symbols appear in `fab_producer.py` and NOWHERE ELSE, gated behind `_fab_closeout_enabled()` (`runner.py:9847`), DORMANT until #288, and `governed_review` plus the governed pre-merge path hold ZERO elision references. Worse, `governed_bundle.py:56` MANUFACTURES the exact `"(empty staged diff)"` sentinel the FAB guard would catch (`return out.stdout.rstrip() or "(empty staged diff)"`) yet nothing on the governed path checks it. Meanwhile `_resolve_artifact` (`panel_invoker.py:846`) returns `artifact or ""` and fails closed only on a MISSING ref path — its own docstring PROMISES "never a silent-empty bundle that would look like a real (empty) review," but that guarantee covers missing, NOT empty: an existing-but-empty file reads verbatim to `""` and sails through — and `PanelLegResult.usable` (`panel_invoker.py:297`) plus `governed_review._findings_from_panel` (keys BLOCK-vs-WARN on `leg.text.strip()`, per `panel_invoker.py:3185`) key on the LEG's text, NEVER on the artifact's substance, so the review authority can approve un-reviewable material on model judgment alone. The obligation: the governed decision points — `_advisor_board_command`'s exit code, `_governed_premerge_review` (`runner.py:10103`) / `_governed_planning_gate` (`runner.py:9802`) blockers — classify empty-or-sentinel reviewed material as a fail-closed BLOCK regardless of how many legs returned a usable AGREE, and this negative direction lives in the SAME suite as the positive path and is NOT gated on `_fab_closeout_enabled()`. Falsified (fires TODAY, no race window — instance 1) by feeding `_advisor_board_command` an empty FILE (it guards `is_file()` at `cli.py:1493` but NEVER non-empty) with ≥`FLOOR_SEATS` usable AGREE legs and observing exit 0 "review passed" rather than a fail-closed BLOCK — the observable is the gate OUTCOME (pass vs BLOCK) on empty material, MECHANISM-AGNOSTIC (any substance check satisfies it, not the `_diff_text_elision` symbol specifically reaching the governed path). Two further constructible instances, all non-FAB: (2) the local closeout gate `_governed_premerge_review` (`runner.py:10103`) — an `"executed"` closeout whose owned paths stage to an empty cached diff embeds the `"(empty staged diff)"` sentinel the gate never elision-checks; (3) `_default_train_review` (`train_runner.py:2002`) reviews `_build_train_review_bundle`'s cross-repo PR-SUMMARY bundle, diff-free BY DESIGN (draft-PR summaries in merge order, never diff bytes), so the predicate would have nothing to key on even if wired. Blast radius stated honestly: currently BOUNDED — FAB's dormant guard backstops live-PR merges and a pathspec-less commit over an empty index fails on the local closeout path, so this is NOT a silent bad-merge TODAY — but the review authority approves un-reviewable material, the only real guard is switched OFF, and NEITHER backstop travels to a new non-FAB merge gate or to FAB's non-live-PR paths. Positive control (two arms, so a blanket always-BLOCK fix cannot pass): (a) the same empty-or-sentinel artifact with a full pool of usable AGREE legs yields BLOCK; AND (b) a NON-EMPTY substantive artifact with the same usable AGREE legs still PASSES — proving the guard keys on emptiness, not on blocking every review. (Distinct from EC-REVIEWTRUTH-12, which is the SEATS approving nothing at the VERDICT layer — an ungrounded AGREE not counted; THIS is the GATE accepting nothing at the MATERIAL layer, model-INDEPENDENT: it fails closed on empty bytes BEFORE any leg verdict is weighed. Sibling of EC-CONFORM-8's rule — a negative-direction guard must NOT be gated on an external dependency, else it is unguarded during exactly the window it can occur; here the external dependency is the #288 FAB flag, and this instance is worse because the guard is not merely absent but written, correct, and switched off.)

**Scope notes**
Decompose into 4 lanes: lane A owns the typed outcome on `PanelLegResult` and publishes
IF-0-REVIEWTRUTH-1 day 1; lane B owns `governed_review._findings_from_panel` consuming it; lane C
owns lens threading into the prompt plus the ratification coverage rule; lane D owns composition
(fillable seat vs lens-distinct backfill) and the typed unfillable signal. `panel_invoker.py` is a
single-writer file — lanes A and D must partition it by function or serialize.

**Non-goals**
Per-repo custom seats and RISCO lenses (LEGLIFE). Leg lifecycle and timeout ENFORCEMENT — killing a
leg on its bound and reaping children — (LEGLIFE lane A). REVIEWTRUTH declares only the typed
`timed_out` OUTCOME variant in `IF-0-REVIEWTRUTH-1`; it does not enforce timeouts.

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
- [ ] EC-PROOFGATE-2 — Recorded mutation evidence whose injection anchor did NOT match is reported as `mutation_not_applied`, never as a pass; falsified by recording evidence whose `assert <anchor> in <source>` fails and finding the run reported PASS — the observable is the `mutation_not_applied` state, not a green result. Positive control: an anchor that DOES match still records a real kill, proving the state is anchor-driven, not always-emitted
- [ ] EC-PROOFGATE-3 — Re-running the validator against ah#358's ORIGINAL acceptance criteria rejects them, since they could not have fired on any motivating incident; falsified by the validator ACCEPTING the ah#358 originals — the observable is a rejection verdict naming the vacuous clause; a green pass on the known-bad corpus is the failure
- [ ] EC-PROOFGATE-4 — A falsifier for a guard must target the PRODUCTION CONSTRUCTION SITE, not only the helper; falsified by unwiring `epoch_blocked` and finding every test still passes
- [ ] EC-PROOFGATE-5 — A parametrized falsifier must be shown to kill EVERY parameter; a surviving parameter is reported; falsified by a parametrized mutation that survives for one parameter while the run reports all-killed — the observable is a per-parameter kill table with a non-empty survivor set, not a file-level pass that hides it
- [ ] EC-PROOFGATE-6 — An acceptance item asserting "X did not happen" must declare its path-entered control; falsified by an "X did not happen" item with no path-entered control validating green — the observable is the validator rejecting the item for a missing positive control, not accepting it
- [ ] EC-PROOFGATE-7 — Legacy plans predating this grammar are grandfathered explicitly, not silently failed; falsified by a pre-grammar plan hard-failed by the new check with no grandfather record — the observable is a warn-level (grandfathered) disposition tagged with the plan's pre-grammar date, not a hard error

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
- [ ] EC-CONFORM-2 — No path emits a submitter-supplied value into serialized output; falsified by, per projection channel, injecting a submitter-controlled sentinel and finding it in that channel's serialized output — the observable is the sentinel bytes surfacing downstream — with the complete channel enumeration recorded and its method stated
- [ ] EC-CONFORM-3 — `redaction_posture="metadata_only"` is emitted only where something enforces it; falsified by removing the enforcement on a path and finding the field still emitted — the observable is `metadata_only` present in output with no enforcing guard on that path. Positive control: a path that DOES enforce still emits it, proving the field tracks enforcement, not a constant
- [ ] EC-CONFORM-4 — The vendored corpus cannot drift silently from its recorded source digests; falsified by mutating one vendored vector byte without updating its digest and finding the drift check green — the observable is a digest-mismatch report naming the drifted file, not silence
- [ ] EC-CONFORM-5 — `outside_agent_pin.py` records a per-schema content digest, so a byte change preserving `…v0.1` is detected; falsified by a byte change to a schema that preserves its `…v0.1` version string while the pin check stays green — the observable is a content-digest mismatch, not the unchanged version string. (Gate CLEARED 2026-07-29 — `spec#102` merged; `agent-harness#377` landed the per-schema digests on `main`, so `outside_agent_pin.py` now RECORDS `submission_schema_sha256`/`verdict_schema_sha256`. This criterion stays LIVE: the recorded digest is mechanism-presence, not proof the CHECK fires — it is satisfied only when a version-preserving byte change is DETECTED, not when the field merely exists.)
- [ ] EC-CONFORM-6 — `phase-plans-v7` OACORE-3 and OAREAL-2 are satisfiable against the MERGED contract (`spec#102` merged 2026-07-29; the "externally blocked" arm is no longer available — the gate is cleared); falsified by either criterion recorded "satisfied" WITHOUT citing the merged contract identity (`spec@v0.2.1`, git sha `b862f977…`, as pinned by `agent-harness#377`) — the observable is a satisfied disposition whose evidence does not resolve to the actually-merged contract. (Re-pointed from the pre-merge falsifier "recorded satisfied while `spec#102` is unmerged," which can NEVER fire now that #102 is merged — a falsifier-that-cannot-fire, re-anchored onto the merged state so it can.)
- [ ] EC-CONFORM-7 — **OUTSIDE-AGENT RELEASE HANDOFF (carried from v7 OARELEASE, `phase-plans-v7.md:277-282`, which v10's table claimed absorbed into CONFORM but left with NO corresponding criterion — so CONFORM could close after materially changing the validator and vendored package surface while the 0.7.13 handoff and inventory went unrefreshed).** The outside-agent release handoff records the EXACT package version or git sha, validator version, contract pin, and vector-manifest hash; release checks and package-surface inventory pass; downstream instructions cover governed-pipeline authoritative pinning and outside-agent advisory usage; and the CHANGELOG distinguishes advisory availability from production merge enforcement. Publish dispatch stays maintainer-owned and is not claimed complete until performed. Falsified by a handoff omitting any of the four identity fields, or a CHANGELOG presenting advisory availability as merge enforcement — the observable is the missing field / the conflated language, not a green test. Positive control: the recorded pin and manifest-hash resolve to the actually-vendored `_contract/` bytes, so a stale or hand-typed hash fails. **GATE CLEARED 2026-07-29** — `spec#102` is merged and the post-merge identity is now KNOWN (`spec@v0.2.1`, git sha `b862f977…`, per-schema digests), so the handoff must describe THAT identity; `agent-harness#377` landed the refreshed handoff on `main`. Stays LIVE: satisfied only when the handoff records all four identity fields resolving to the merged contract, not merely when #377 landed
- [ ] EC-CONFORM-8 — **ADVERSARIAL VECTORS STILL FAIL CLOSED AFTER THE #371 DIALECT CHANGE (positive-carried / negative-dropped, restored from v7's fail-closed obligations `phase-plans-v7.md:80,126-130,227-231` — "Unknown fields, unsupported versions, absolute paths, missing digests, raw payloads, and path traversal fail closed").** EC-CONFORM-1 asserts ONLY that the 3 canonical VALID vectors PASS; NO criterion asserts the corpus's invalid/adversarial vectors are still REJECTED, so the #371 validator-dialect change can over-accept — the exact fail-open direction #371 was fixing — while every exit criterion stays green. Every invalid vector in the vendored corpus (unknown field, unsupported schema/contract version, absolute path, missing digest, raw payload, path traversal, malformed submission — plus the `invalid-empty-evidence-refs` and `invalid-git-object-id-length` vectors agent-harness#372 adds at spec `v0.2.1`) runs through `run_outside_agent_vectors` and yields `expected_status == blocked` WITH each `expected_blocker_codes` entry present in the live verdict; the accept-direction (EC-CONFORM-1) and this reject-direction live in ONE suite so they move together and a dialect edit cannot relax one without the other going red. Falsified by, per adversarial vector, the #371 (or any later) dialect change relaxing the validator so that vector returns PASS or drops its expected blocker code while the suite stays green — the observable is a corpus vector whose recorded `expected_status: blocked` no longer matches the live verdict, i.e. a submission the contract forbids being admitted. Positive control: the 3 canonical VALID vectors still PASS in the same run, proving the reject-direction is discriminating rejection and not a blanket fail-closed that would also sink valid submissions. NOT externally gated — the adversarial vectors are in the vendored corpus today and `run_outside_agent_vectors` exercises the blocked-direction now, so gating this on `spec#118` would leave the over-accept regression unguarded during exactly the window it can occur

**Scope notes**
Decompose into 2 lanes: lane A owns the validator dialect, redaction separation, the
projection-channel enumeration, and the adversarial-vector reject-direction guard
(EC-CONFORM-8; agent-harness#372 is in flight and refreshes the corpus to spec `v0.2.1`); lane B
owns the pin digest work and the v7 criterion disposition (EC-CONFORM-6 and EC-CONFORM-7).
**EC-CONFORM-5, EC-CONFORM-6, and EC-CONFORM-7 are NO LONGER externally gated — the gate CLEARED
2026-07-29** (`spec#102` merged, `spec#118` closed, `agent-harness#377` landed the `v0.2.1` pin +
per-schema digests + refreshed handoff on `main`). Lane B now closes them against the merged
contract (`spec@v0.2.1`, sha `b862f977…`); each stays LIVE and falsifiable — landing #377 records
the mechanism, it does not by itself SATISFY the acceptance falsifier (a drift-detecting check for
`-5`, a merged-contract-cited disposition for `-6`, a four-field handoff for `-7`). **EC-CONFORM-8 is NOT externally gated** — it guards lane A's own dialect change
against over-acceptance and is testable against the vendored corpus today; gating it on the
external contract would leave the regression unguarded during exactly the window it can occur.

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
- [ ] EC-FABPUB-4 — A faithful post-crash publish retry DEDUPS rather than re-allocating. The publish idempotency key is `publish_committed_branch_idempotency_key(repo, branch, head_sha)` (`broker/verbs.py:25,31`); a retry with the same `(repo, branch, head_sha)` must resolve to the recorded effect via the `idempotency_key` equality at `broker/admission.py:46` and return the prior admission, never allocate a second. Falsified by mutating the dedup-key derivation to fold `attempt_id`/`uuid4` into the publish key (or forcing the `admission.py:46` idempotency-key equality to `False`), then replaying crash-then-retry with identical `(repo, branch, head_sha)` — the observable is TWO admission records / two published references for one committed head, not one deduped effect. Positive control: a publish of a genuinely different `head_sha` DOES allocate a fresh admission, proving the key discriminates on committed identity rather than blanket-suppressing retries
- [ ] EC-FABPUB-5 — A legitimate post-crash retry is NOT rejected by the conflict comparison; this is the failure mode the round-2 fix introduced; falsified by re-introducing the round-2 over-strict conflict comparison and finding a genuine same-fields post-crash retry REJECTED — the observable is the retry raising a conflict where it should dedup. Positive control: a truly conflicting retry (different authority) is still refused, proving the comparison was loosened, not disabled
- [ ] EC-FABPUB-6 — A conflicting resume (same attempt_id, different authority) is REFUSED; positive control: a genuine same-fields resume still dedups; falsified by removing the authority check and finding a different-authority resume ADMITTED under the same attempt_id — the observable is the admission record, not a refusal
- [ ] EC-FABPUB-7 — Publish byte-neutrality is explicitly RETRACTED in the CHANGELOG, not claimed alongside renumbering; falsified by a CHANGELOG that claims byte-neutrality (or omits the retraction) while the renumbering lands — the observable is a byte-neutrality claim co-present with the epoch renumbering, not the explicit retraction sentence

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
- [ ] EC-FABREADMIT-2 — A revoked FRESH delta re-admit does not merge; the assertion is the desired behaviour and is paired with a non-revoked reachability control proving the seam was entered; falsified by removing the revocation check on the FRESH path and finding a revoked delta merges — the observable is the merge completing despite an OUTCOME_AMBIGUOUS_BLOCKED/revoked marker. Positive control (the pairing): a non-revoked delta on the same path DOES merge, proving the seam was entered and the block is revocation-specific
- [ ] EC-FABREADMIT-3 — A revoked CRASH-RESUME re-admit does not merge; same pairing, targeting the early append specifically; falsified by removing the revocation re-check on the crash-resume early-append path and finding a revoked resume merges — the observable is the early append completing despite revocation. Positive control: a non-revoked crash-resume still merges via the early append, proving that seam was entered
- [ ] EC-FABREADMIT-4 — The engagement flag cannot be enabled while any publisher still stamps a hardcoded epoch; falsified by leaving a publisher that stamps a hardcoded epoch and finding the flag can still flip True — the observable is the interlock refusing the flip (a raise/guard) while any hardcoded-epoch stamp remains, not a silent enable
- [ ] EC-FABREADMIT-5 — The enumeration of head-advancing append sites is recorded with a re-runnable method, so a future third site is detectable; falsified by adding a third head-advancing append site and finding the recorded method does not surface it — the observable is the enumeration method (a re-runnable grep/AST scan) listing the new site, not a hardcoded two-site list
- [ ] EC-FABREADMIT-6 — **The delta-review shortcut ACTUALLY ENGAGES.** `_FAB_DELTA_BROKER_READMIT_READY` is flipped True and `fab_delta_shortcut_enabled()` returns True under production conditions, proven by an end-to-end test in which the shortcut FIRES — not merely that it is permitted to. Falsified by reverting the flag, after which that test must fail. **Note: EC-FABREADMIT-4 is a NEGATIVE-ONLY criterion — "the flag cannot be enabled prematurely" is satisfied by never enabling it, which would leave agent-harness#191 permanently dormant. This criterion supplies the positive case.**
- [ ] EC-FABREADMIT-7 — agent-harness#191 (FAB delta review with reviewed-byte equivalence) is closeable: the consumer merged DORMANT in `ecd1258` is live, and the reviewed-byte-equivalence shortcut runs on a real delta; falsified by the shortcut path never executing on a real delta (flag still False or consumer unthreaded) while #191 is marked closeable — the observable is an end-to-end run recording the shortcut FIRING on a real delta, not merely that the consumer symbol is present

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
- [ ] EC-SCHED-2 — `test_create_is_idempotent_after_stale_worktree` no longer pins data loss as intended behaviour, and its replacement assertion is recorded as a ratified decision; falsified by the test still asserting the destructive path as intended, or a replacement landing with no recorded ratified decision — the observable is the test asserting preservation (not deletion) plus a decision-record reference
- [ ] EC-SCHED-3 — A worktree whose only content is a gitignored handoff is not treated as empty; falsified by presenting a worktree containing only a gitignored handoff and finding the emptiness check reclaims it — the observable is the check classifying it non-empty (handoff detected), not empty
- [ ] EC-SCHED-4 — The lane scheduler honours `work_unit_kind`, so a reducer lane is not dispatched as an executor; falsified by dispatching a `work_unit_kind=reducer` lane and finding it launched on the executor path — the observable is the dispatch decision reading `work_unit_kind` and routing to the reducer path
- [ ] EC-SCHED-5 — Validated planner artifacts survive parent reduction under `--phase-scheduler concurrent`; falsified by running a concurrent reduction and finding validated planner artifacts destroyed or overwritten — the observable is the artifact files present and byte-unchanged after reduction. Positive control: the reduction still runs (a preservation-merge, not a skipped reduction), proving survival is not achieved by declining to reduce
- [ ] EC-SCHED-6 — After a no-diff concurrent dispatch, the parent does not run phase verification against files that were never created; falsified by a no-diff concurrent dispatch triggering parent verification against absent files — the observable is verification being SKIPPED (or a typed no-diff signal raised) rather than failing on missing paths. Positive control: a dispatch that DID produce a diff still runs verification, proving the skip is diff-conditioned, not unconditional
- [ ] EC-SCHED-7 — **WORKTREE-LOSS DISPOSITION (carried from v9 FAB lane (a), `phase-plans-v9.md:357`; v9's banner recorded it as "CANNOT-DETERMINE, not carried" (`v9:16`), and superseding v9 would otherwise make its acceptance condition silently unreachable — "cannot-determine" is not a disposition).** v9:357 required each of four divergent worktrees — `agent-harness-abdreg`, `ah-abdreg-pkg`, `ah-abdreg-rebase` (three copies on `feat/advisor-board-abdreg`) and `agent-harness-abdresolve` (`phase/abdresolve`) — to be landed, committed-and-parked, or explicitly discarded with a recorded decision, no silent loss. The verifiable, satisfiable obligation carried here is PRESERVATION OF THE SURVIVING COMMITTED TIPS (verified 2026-07-29, aligned to `plans/design-fab-191-delta-review.md:514-521`, NOT smoothed): NONE of the four worktrees still exists under `git worktree list`, and both branches `feat/advisor-board-abdreg` (`4c603c3`) and `phase/abdresolve` (`582037e`) survive on `origin` (confirmed by `git ls-remote`), so their committed state is parked-and-recoverable. Satisfied by those two `origin` tips confirmed retained under a recorded disposition. Falsified by either `feat/advisor-board-abdreg` or `phase/abdresolve` being deleted from `origin` with no recorded decision — the observable is the missing ref, a silent loss of committed state. STANDING FINDING (STATE, not satisfaction — this criterion does NOT turn green by recording it, and it is NOT satisfied by admitting the loss): the `phase/abdresolve` worktree's 25 uncommitted files were **discarded UN-INSPECTED** — whether they were re-appearing already-committed work or genuine un-committed progress is UNKNOWABLE, and the FAB design record `design-fab-191-delta-review.md:514-521` explicitly DECLINES to claim "no silent loss" for them — so v9:357's no-silent-loss is UNMET for `abdresolve`, carried as an accepted possible-loss exactly like EC-INTEG-5's 2-of-N residual, never a green. (The `abdreg` copies' 5 uncommitted files were by contrast INSPECTED — sibling copies reverting committed safety fixes, an abandoned experiment, no value forgone — a genuine recorded discard, outside the standing finding.)

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
- [ ] EC-LEGLIFE-1 — A leg exceeding its bound is killed and reported as the typed `timed_out` variant frozen in `IF-0-REVIEWTRUTH-1` — not silence, and not a DIFFERENT status; falsified EITHER by removing the enforcement, after which a leg runs past its cap, OR by killing a bound-exceeding leg but reporting it under any status OTHER than `timed_out` (e.g. `errored` or `unavailable`) — the observable is a killed-past-cap leg carrying the `timed_out` variant that `EC-REVIEWTRUTH-7` routes to retry. This second arm is the composition guard: `EC-REVIEWTRUTH-7` validates only against a SYNTHESIZED frozen `timed_out`, so a timeout enforced HERE but emitted under the wrong status would pass `-7` and pass a "something was reported" reading of THIS criterion while the end-to-end path is broken — the wrong-status mutation must fire here or the interface-freeze cut of the LEGLIFE→REVIEWTRUTH cycle is a rename, not a resolution. Positive control: a leg that completes WITHIN its bound is NOT reported as `timed_out`
- [ ] EC-LEGLIFE-2 — The aggregate always returns, and no provider subprocess outlives it; falsified by disabling the child-reaping and finding a provider subprocess alive after the aggregate returns — the observable is a zero live-child count once the aggregate returns, and the aggregate returning even when a leg hangs (not blocking on it)
- [ ] EC-LEGLIFE-3 — A supported single-leg entry point exists; documentation stops instructing operators to re-implement leg mechanics; falsified by the single-leg entry point being absent while docs still hand-roll leg mechanics — the observable is a callable public entry point exercised by a test, not a documentation snippet
- [ ] EC-LEGLIFE-4 — A repo can declare custom seats and lenses that reach the reviewer's prompt; falsified by declaring a custom seat+lens and finding neither in the rendered reviewer prompt — the observable is the custom lens string present in the assembled prompt for that seat
- [ ] EC-LEGLIFE-5 — The gemini/agy seat receives equivalent material to repo-access seats, or the asymmetry is recorded in the verdict; falsified by the gemini/agy seat receiving less material than repo-access seats with no asymmetry note in the verdict — the observable is either byte-equivalent seat material or a recorded asymmetry flag on the verdict, never a silent gap
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
- [ ] EC-HARDEN-2 — Path handling in the reconcile main loop is CWD-independent; falsified by invoking the reconcile main loop from a different CWD and finding a path resolves differently — the observable is identical resolved paths across two CWDs, where a relative-path use would diverge
- [ ] EC-HARDEN-3 — Goal-coverage enforce mode fails closed rather than passing vacuously when no EC-IDs are declared; falsified by running enforce mode with zero declared EC-IDs and finding it PASSES — the observable is a fail-closed error on empty declarations, not a vacuous green
- [ ] EC-HARDEN-4 — The login-shell interpreter shim resists the exotic bash-option and profile-introduced-version forms recorded in ah#241; falsified by feeding each ah#241 form (exotic bash-option, profile-introduced version) and finding the shim selects a non-satisfying interpreter — the observable is a fail-closed rejection per form, enumerated, not a silently-shadowed interpreter
- [ ] EC-HARDEN-5 — **FLEET-WIDE REVIEW-LEG ISOLATION (ah#248; v10's first draft allowed satisfaction by an "explicitly operator-accepted residual with a recorded rationale," which marks the criterion MET while a review leg can still execute — the roadmap reports green with the hazard live).** Review-leg isolation is a SAFETY INVARIANT, not residual-risk hardening: review bundles are attacker-controlled by construction, which is the whole reason review legs are refused execution capability — a review leg that can execute, can execute regardless of what any register records. The obligation, per the ah#248 isolation standard, is that a review leg holds no mutation capability: it cannot issue a repository mutation or any credentialed/privileged side-effect from the review-leg environment. (A read-only review leg legitimately spawns its own reviewer subprocess — the bar is the absence of mutation/credentialed side-effects, NOT absolute-zero process or shell execution; the earlier "cannot spawn a process or run a shell command" wording overshot ah#248 and no correct read-only leg could satisfy it.) Falsified by a review leg that issues a repository mutation or a credentialed side-effect despite the standard — the observable is a successful mutation/credentialed operation issued from a review-leg environment, NOT the mere spawning of a process and not the presence or absence of a residual-register entry. This criterion is satisfied ONLY when the isolation checklist is fully met, full stop — it is a safety invariant and is NOT satisfiable by documenting its own failure. An operator genuinely may accept a security residual, but that belongs in the STATE, not the SATISFACTION: the standard is then UNMET with an accepted residual, carried here as a STANDING FINDING exactly like EC-INTEG-5's 2-of-N — never "met because we wrote it down." Its honest state: if the fleet-wide checklist is not fully met, this is UNMET and any residual recorded in the accepted-residual register (ah#361) is that standing finding, not a green

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
- [ ] EC-RESIDUAL-1 — `publish_committed_branch` dedup keys include `base`, so a cross-base replay cannot skip the base scope-check; falsified by removing `base` from the dedup key and replaying the same branch across two bases, finding the second skips its scope-check — the observable is the dedup key tuple containing `base`, so the second replay re-runs the check
- [ ] EC-RESIDUAL-2 — A live-head-read failure on the pr_open resume path yields a typed blocker rather than an uncaught abort; falsified by injecting a live-head-read failure on pr_open resume and finding an uncaught exception — the observable is a typed blocker outcome, not a traceback abort. Positive control: a successful head read still resumes, proving the path is exercised
- [ ] EC-RESIDUAL-3 — The null-oid merge-queue false-halt is closed for non-FAB repos, not only FAB-scoped nodes; falsified by a null-oid on a non-FAB node halting the queue — the observable is the queue proceeding (null-oid handled) on a non-FAB repo, not only on FAB-scoped nodes
- [ ] EC-RESIDUAL-4 — `phase-loop hotfix` refuses or correctly executes a `verification_command` containing shell operators; a false green is impossible; falsified by a `verification_command` with `;`/`&&`/`|` producing a green while the real command failed — the observable is either a refusal or a faithful non-zero exit, never a false pass
- [ ] EC-RESIDUAL-5 — An unbound channel session model is recorded and refused on mismatch, and no handoff or status surface reports it uncaveated; falsified by an unbound channel session model passing a status/handoff surface uncaveated, or a mismatch being admitted — the observable is a refusal on mismatch and a caveat marker on every surface, not a bare report
- [ ] EC-RESIDUAL-6 — A repair child cannot recursively launch repair, and an interruption cannot overwrite a trusted closeout; falsified by (a) a repair child launching a nested repair — observable: a second repair invocation in the child's process tree — or (b) an interruption overwriting a trusted closeout — observable: the closeout bytes changed after an interrupt. Positive control: a top-level repair still launches normally, proving recursion is what is blocked, not repair itself
- [ ] EC-RESIDUAL-7 — The 28 deferred F841 findings are triaged and either fixed or individually justified; falsified by an F841 finding among the 28 that is neither fixed nor carries an individual justification — the observable is a triage table covering all 28 with a per-finding disposition, not a blanket deferral

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
- [ ] EC-RUNTIME-0 — **TEST LANE LANDED FIRST.** Tests written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier RUN with its injection anchor asserted; the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-RUNTIME-1 — An append-only event log persists intent-before and outcome-after records per side-effect; falsified by dropping the intent record, after which a crash between intent and outcome is indistinguishable from no attempt
- [ ] EC-RUNTIME-2 — The reconciliation engine resolves exact live Git/GitHub/provider AND REGISTRY state (not cached) and emits the IF-0-FREEZE-5 authority verdicts + invalidation triggers on divergence (REGISTRY state, the authority verdicts, and the invalidation triggers are restored from `convergence-v1:252-253` — "Reconciliation engine resolves exact live Git/GitHub/provider/registry state and emits the IF-0-FREEZE-5 authority verdicts + invalidation triggers" — which v10's paraphrase had narrowed to Git/GitHub/provider with no verdict or trigger, the reworded-weaker-form shape; this is the TENTH recovered drop / the eleventh candidate, the tenth having been the REFUTED `v4:217`); falsified by (a) stubbing any live read — Git, GitHub, provider, OR registry — and the divergence going undetected; OR (b) a run that reconciles Git/GitHub/provider but NOT release-registry state, so a registry divergence is left unreconciled with NO authority verdict emitted and NO invalidation trigger fired — the observable is a real registry-state divergence that produces no frozen IF-0-FREEZE-5 verdict and no invalidation trigger, NOT the mere presence of an "emits" call. Positive control: a genuine live reconciliation across all FOUR domains emits the authority verdicts and fires the invalidation trigger on an actually-divergent registry, proving the registry arm and the verdict/trigger emission are load-bearing, not a blanket emit on every run
- [ ] EC-RUNTIME-3 — Codex, Claude, and at least one outside-agent adapter return the frozen envelope shape AND carry expected-version predicates, and NONE of them coordinates the train (the expected-version predicate and "none coordinates" are restored from `convergence-v1:254-255`, which v10's paraphrase had dropped); falsified by an adapter that omits a required envelope field or its version predicate, or one that drives coordination — the observable is the missing envelope field / the absent version predicate / a coordinator call originating from an adapter
- [ ] EC-RUNTIME-4 — `train-status` reconstructs train state from the ledger with no transcript available; falsified by deleting the transcript and stubbing the cache, then finding `train-status` returns empty or errors instead of reconstructing from the ledger — the observable is the reconstructed state matching the ledger contents with no transcript present
- [ ] EC-RUNTIME-5 — The `convergence-v1` plan files (`plans/phase-plan-vergence-v1-RUNTIME.md`) are re-grounded against current main before execution, or explicitly superseded — they were authored 2026-07-13 and the runtime has moved considerably; falsified by executing the 2026-07-13 plan file with no re-grounding record against current main — the observable is a re-grounding decision citing the current main SHA (or an explicit supersession), not the stale plan run as-is

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
- [ ] EC-INTEG-0 — **TEST LANE LANDED FIRST.** Tests written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier RUN with its injection anchor asserted; the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-INTEG-1 — The coordinator drives side effects only through the broker; falsified by restoring any direct-credential path, which must be detected
- [ ] EC-INTEG-5 — **PROCESS-BOUNDARY CREDENTIAL ISOLATION (restored from `convergence-v1:291-293`; v10's first draft narrowed it to a two-env-var-name check that passes while credentials remain fully available).** The obligation is that the broker is the ONLY process holding mutation credentials — not merely that two env var names are absent. `gh` and `git` authenticate through MANY channels: the `GH_TOKEN`/`GITHUB_TOKEN` env vars, the `gh` config token in `hosts.yml`, the OS keyring, an SSH agent, git credential helpers, `GIT_ASKPASS`/`SSH_ASKPASS`, and `~/.netrc`. A spawned coordinator/worker must be unable to mutate through ANY of them. Falsified by, per channel, a spawned worker that can still authenticate through that channel — the observable is a successful `gh`/`git` mutation issued from the worker environment, not the mere presence or absence of an env var. **FINDING the roadmap must carry, not write around: `BrokerEnvironmentBoundary` (`convergence/broker/credsep.py`) today strips only `GH_TOKEN`/`GITHUB_TOKEN` — 2 of the N channels above — and has ZERO production constructors: `cli.py:3654` builds the live broker INSIDE the coordinator process, and executor environments copy `os.environ` stripping only Claude markers (`harness_env_signatures.py:194`, `launcher.py:2250`). The implementation covers 2 of N channels and does not currently hold the isolation.** This criterion is satisfied ONLY when every channel above is closed for spawned processes — it is a safety invariant and is NOT satisfiable by documenting its own failure. Its honest state today is UNMET: the 2-of-N finding above is a STANDING FINDING, not an accepted residual. A safety invariant may be carried as currently-false (that is the honest disposition here); it may never be marked met because the residual gap is written down and operator-accepted, which would let the roadmap close while spawned workers can still mutate repositories. EC-INTEG-1 alone cannot detect this: routing through a broker *abstraction* passes while the isolation does not hold
- [ ] EC-INTEG-6 — **PRODUCTION WIRING OF THE ABSORBED COORDINATOR OBLIGATIONS (restored to `convergence-v1:340-353`; v10's first draft narrowed this to greppable-presence — "a production call site asserted by a test" passes with the call sitting behind a permanent `False` flag, on a dead branch, or in a helper nothing invokes).** The obligation is behavioural, on a live `run_train` path: (a) reconciliation runs before EVERY dispatch/resume/publish/review/merge/release and its verdict GATES the action — falsified by making the reconcile a no-op returning stale-cached state, whose observable is a dispatch proceeding against a live-diverged head the reconcile should have caught (not "the symbol `reconcile_before_action` is referenced"); (b) a record whose schema/transition/invalidation version the coordinator does not support is REJECTED, never coerced (D4) — falsified by feeding an unsupported-version record, whose observable is acceptance instead of a typed rejection; (c) after an upstream merge, each affected downstream branch is auto-refreshed (or a typed conflict raised), re-verified against the merged SHA, republished, and its prior review invalidated — falsified by removing the refresh, whose observable is a downstream merged against a stale base carrying a still-valid prior review. Positive control (the seam is ENTERED, not merely present): a live `run_train` with two dependent nodes records, in the event log, a reconcile entry before each of the six action kinds and a downstream-refresh entry after the upstream merge — a symbol appearing in a source file does not satisfy this; the ledger must show the calls FIRED. (`reconcile_before_action`/`dispatch_ready_nodes`/`refresh_downstream_after_merge` today have ZERO production callers — definition and `convergence/__init__.py` exports only.)
- [ ] EC-INTEG-2 — Crash injection between broker admission and ledger append converges on resume rather than double-executing; falsified by removing the idempotency-key guard and finding resume RE-EXECUTES the admitted effect — the observable is an effect count of 2 across the crash+resume, not 1. Positive control: the crash is actually injected at the admission→append gap (the kill point is asserted entered), so single-execution is proven under a real crash, not a skipped one
- [ ] EC-INTEG-3 — The adversarial fault suite covers revocation mid-operation, ambiguous terminals, concurrent same-target requests, AND the `convergence-v1:388-399` families v10's paraphrase dropped — the delayed-provider-commit matrix, mixed-version/exact-head faults, and the D2 outside-agent adversarial set (forged completion evidence, malformed result envelope, capability overclaim, stale/delayed seat write, action-outside-bounds) — each detected and fail-closed BEFORE any pilot; falsified by, per family, removing that family's guard and finding the fault admitted rather than blocked — the observable is the fail-closed outcome (a typed block/raise) for each named fault, not the presence of a test file naming it
- [ ] EC-INTEG-4 — `plans/phase-plan-vergence-v1-FAULTS.md` — hand-executed 2026-07-26 with 138 fault tests green — is reconciled into the ledger rather than left as bookkeeping-stale; falsified by the 138 green fault tests existing only as a markdown/hand-run record with no corresponding ledger reconciliation entry — the observable is a ledger entry binding the FAULTS closeout to the actual run, not a prose file
- [ ] EC-INTEG-7 — **CONCURRENT-ADMISSION ISOLATION PREDICATE (restored from `convergence-v1:343-347`; carried by NO v10 criterion before this — a dropped obligation of the same MERGED-IS-NOT-REACHABLE / fail-closed-softening class the earlier drafts kept reproducing).** Before two independent DAG nodes are admitted concurrently under their per-repo locks, the pair MUST pass the IF-0-FREEZE-6 isolation predicate (disjoint owned-paths + frozen interfaces); a pair that fails it is SERIALIZED, not admitted, and the fail-closed decision is persisted to the event log. Topo merges and release publication are ALWAYS serialized. Falsified by presenting a concurrent unit-pair with OVERLAPPING owned-paths and finding both admitted in parallel — the observable is admission of the second unit while the first holds an overlapping path, where the obligated behaviour is serialization plus a persisted predicate-false event; the fail-closed direction (predicate-false ⇒ serialize) must be tested independently of the predicate-true path so a predicate hard-wired to True cannot pass. Positive control: a genuinely disjoint pair IS admitted concurrently, proving serialization is predicate-driven, not a blanket serial fallback

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
- [ ] EC-RELEASE-0 — **TEST LANE LANDED FIRST.** Tests written, PANELED, and observed RED against the pre-implementation base before any production change; each names a falsifier RUN with its injection anchor asserted; the implementation PR does not modify them. Falsified by an implementation commit predating the test commit, or a test diff inside the implementation PR.
- [ ] EC-RELEASE-1 — At least two parallel pilot trains complete with broker-mediated side effects and no direct-credential path; falsified by a pilot counted complete while a side effect took a direct-credential path bypassing the broker — the observable is every pilot side effect carrying a broker admission/evidence record read from the ledger; a bare completion claim without that evidence fails. Positive control: broker mediation is read from the ledger, not asserted in prose
- [ ] EC-RELEASE-2 — Pilot evidence is machine-checkable, not prose asserting that a live run occurred; falsified by a test that string-matches a markdown evidence file, which must be rejected
- [ ] EC-RELEASE-3 — The release declares its production status honestly (`pilot-ready` / `deployed-not-baked` / `production-ready`) and does not overclaim; falsified by `production-ready` emitted while the recorded count of post-release converged trains is zero — the observable is the status string gated on the converged-train evidence count, not a free-text label
- [ ] EC-RELEASE-4 — Version bump, CHANGELOG, and RELEASE_PIN agree; the tag push that triggers OIDC publish remains user-gated; falsified by desynchronising one of {`pyproject` version, `__init__` version, CHANGELOG, RELEASE_PIN} and finding the agreement check green, or by an automated (non-user-gated) tag-push path — the observable is the four version values compared equal AND the tag-push step requiring a human gate
- [ ] EC-RELEASE-5 — **RELEASE PUBLICATION-COMPLETION (restored from `phase-plans-convergence-v1.md:468-471`, which v10's first draft dropped by declaring publishing a Non-goal and reducing the RELEASE bar to "any two pilots plus four version-string agreement" — so RELEASE could close while the package was never published, the fleet never upgraded, and the HEAD-install workarounds never removed).** User-gating the publish is legitimate SEQUENCING; omitting the publication OUTCOME from SATISFACTION is not (codex, r4). Beyond EC-RELEASE-4's version-VALUE agreement, RELEASE is complete only when: the required cross-vendor board reviewed the EXACT merged heads with substantive dissent resolved; the OIDC publish was PERFORMED (maintainer-gated, and not claimed complete until performed — the EC-CONFORM-7 posture); the fleet pin was upgraded and the HEAD-install workarounds removed; and the released PACKAGE identity == the installed COMMAND identity == the fleet PIN (a runtime three-way equality, distinct from EC-RELEASE-4's source-of-truth version-string equality). Falsified by RELEASE marked complete while (a) the OIDC-publish step carries no recorded execution evidence, (b) a HEAD-install workaround remains in the fleet pin, or (c) the three identities diverge — the observable is the missing publish-execution record / the surviving workaround / the identity mismatch, not a green version-agreement check. Positive control: the three identities are read from the actually-published package, the installed command, and the fleet pin — not asserted in prose. (Publish dispatch stays maintainer-owned; this criterion is prepared but not closed until the publish is performed.)
- [ ] EC-RELEASE-6 — **NAMED KEYSTONE + OUTSIDE-AGENT PILOTS WITH AMBIGUITY METRICS (restored from `convergence-v1` PILOT exit criteria, `phase-plans-convergence-v1.md:430-437`, whose keystone SPECPKGMIN is named at `:425-426`; v10's `EC-RELEASE-1` reworded this to "at least two parallel pilot trains complete" — satisfiable by ANY two pilots, the canonical "criterion survives in reworded, weaker form that reads as carried" drop, the NINTH).** `EC-RELEASE-1` staying generic is fine; this criterion carries the specifics it shed, kept separate so `EC-RELEASE-1`'s generic-completion falsifier and this named-keystone falsifier each stay clean. RELEASE's pilot bar is met only when: the keystone **SPECPKGMIN** pilot lands the built 3-repo slice via the broker `publish_committed_branch` path as 3 COORDINATED draft PRs (ledger + `train-status` consistent, interchange verification preserved with NO fresh re-execution, stopping at `drafts_open`); the **outside-agent** pilot exercises capability admission with the `needs_clarification`/`review_candidate`/`reject` verbs actually fired; and **time-in-ambiguous-block is tracked**, with NO auto-failover for providers lacking terminal completion semantics. Falsified by RELEASE marked complete while (a) no SPECPKGMIN broker-`publish_committed_branch` 3-draft-PR evidence exists, (b) the outside-agent pilot never drove the `needs_clarification`/`review_candidate`/`reject` admission transitions, or (c) no time-in-ambiguous-block metric was recorded — the observable is a "complete" RELEASE resting on `EC-RELEASE-1`'s any-two-pilots bar with none of the named-keystone artifacts, i.e. the IF-0-PILOT-1 evidence bundle absent or generic. Positive control: the pilot evidence bundle records the SPECPKGMIN 3-PR broker publish, the three admission verbs having fired on the outside-agent pilot, and the ambiguous-block timing — proving this is the named keystone, not any two trains. (Distinct from EC-RELEASE-1 generic pilot completion and EC-RELEASE-5 publication-completion; this is the pilot-EVIDENCE gate. Draft-PR opening is outward and maintainer-coordinated per INV-5.)

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
CONFORM ──────────────┤   [gate CLEARED 2026-07-29 — spec#102 merged, #377 landed the pin]
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
| ~~`Consiliency/spec` PR #102 ratify-or-supersede~~ **RESOLVED 2026-07-29** (merged; `#118` closed; `agent-harness#377` pinned `v0.2.1`) | ~~EC-CONFORM-5/6/7~~ no longer blocked — re-derived against merged sources | `spec#102` merged / `agent-harness#377` |
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
