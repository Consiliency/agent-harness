# Scoping & plan: goal-ID single source of truth (redefines Consiliency/agent-harness#211)

## Problem reframe

#211 was scoped as "audit that the plan's acceptance criteria still cover the
roadmap's exit-criteria" — a text-diff between two lists. Three cross-vendor CR
rounds proved that audit undecidable: catching semantic *weakening* by comparing
words has, at every tuning, either a false-positive (blocks a valid refinement) or
a fail-open (misses a real weakening). The failure is structural, not a bug: there
are **two sources of truth** (the roadmap goal and the plan's re-statement of it),
and the gap between the copies is where weakening hides.

**This redesign removes the duplication instead of policing it.** The roadmap goal
becomes the single source of truth with a stable ID; the plan's acceptance item
*references* the goal ID + names its proving evidence, rather than re-stating the
goal in (potentially weaker) words. Drift-by-restatement then cannot occur — the
plan never rewrites the goal.

## What this does and does NOT guarantee (honest scoping — read first)

- **Deterministically DETECTS a forgotten goal (decidable):** every roadmap goal
  ID must be referenced by ≥1 plan acceptance item; an unreferenced goal ID is
  reported with certainty (no word-matching). It **prevents** the omission only
  under block enforcement (warn-default *detects and surfaces*). To make "no goal
  silently dropped" hold, activation is **all-or-none per phase** — an opted-in
  phase must carry an EC-ID on *every* exit-criterion (a mixed EC-ID + bare-prose
  phase is a `roadmap_lint` error, `contract_bug`); otherwise a newly-added
  bare-prose criterion is exactly the old dropped-goal hole (CR: all three seats).
- **Does NOT guarantee ADEQUACY:** it does not verify that the referenced evidence
  actually discharges the goal. `EC-P1-1` ("publish **non-silent** audio")
  referenced by `proven by test_audio_track_exists` passes the completeness check
  even though the test only checks a track exists. What the reference *buys* for
  the weakening class is that the goal is now pinned **next to its claimed
  evidence**, so weak evidence is **human-reviewable at the point of reference** (a
  CR reviewer / the #91 evidence-authenticity gate), instead of hidden in a
  reworded paraphrase. Weak-evidence detection is explicitly **out of scope** and
  stays with CR + #91.
- It also does **not** verify that N plan items *sum to* a coarse goal — only that
  the goal is referenced at all.

State this plainly in every downstream artifact; overselling "drift is impossible"
is the exact framing that treadmilled the fuzzy audit.

## Empirical grounding (sampled real roadmaps)

Sampling exit-criteria across `specs/phase-plans-v{1,2}.md` + the sourcebroker
roadmap: **real exit-criteria are already concrete, testable assertions, and many
already cite their proving command** (roadmap-builder enforces "testable assertion,
checkable by shell command, not vibes"). So the plan's acceptance criteria today
are largely near-duplicate restatements — validating both that the duplication is
the drift surface and that a **reference-only** model fits the common case. A
minority are coarse or bundle multiple checks (sourcebroker "…are tested"; v2's
"Routing-invariant tests pass: [6 invariants]"), so the design supports **1:many**
(one goal ID referenced by several plan items) but treats refinement as the
exception, not the norm.

## Design

### The `EC-<ALIAS>-<N>` scheme (mirrors the proven `IF-0-<ALIAS>-<N>` gates)

Each roadmap phase exit-criterion gets a stable ID `EC-<ALIAS>-<N>` (alias = the
phase alias, N = a positive int), mirroring the IF-gate scheme's alias-scoping +
uniqueness. **IDs are stable identities, not positions.** The lint statically
enforces what a single snapshot can: **alias-scoped + unique + gaps-allowed** (NOT
contiguous). Allowing gaps is what makes non-reuse *possible* — deleting `EC-P1-2`
does not force renumbering `EC-P1-3`, so a downstream plan's `EC-P1-3` reference
stays bound to the same goal. **"Never reuse a deleted ID for a different goal" is an
authoring DISCIPLINE the static lint cannot verify** (it has no history of prior
snapshots — CR codex round 8, honestly scoped). The tool removes the *pressure* to
renumber; it cannot detect a malicious/careless historical rebind.

**All-or-none activation:** within a phase, either *every* exit-criterion carries an
`EC-<ALIAS>-<N>` ID (opted-in → coverage enforced) or *none* do (legacy → no gate).
A phase mixing ID'd and bare-prose exit-criteria is a `roadmap_lint` error — this
closes the mixed-mode hole where a bare criterion would be ungated.

```
### Phase 1 — Closeout gates (P1)
**Exit criteria**
- [ ] EC-P1-1 — `register_closeout_validator(fn, severity)` exists and … (`pytest -k closeout`)
- [ ] EC-P1-2 — no validator path can set `human_required=true` (test asserts …)
```

Recon-confirmed this is non-breaking: `roadmap_lint._checkbox_items` returns the
whole post-`- [ ] ` remainder, so `EC-P1-1 — <assertion>` parses today; only a new
validator enforces the ID. No frozen roadmap-format contract exists.

### The plan references, never restates

```
## Acceptance Criteria
- [ ] EC-P1-1 — proven by `pytest tests/test_closeout.py -k register_validator`
- [ ] EC-P1-2 — proven by `tests/test_closeout.py::test_no_human_required`
- [ ] (plan-internal) no new lint errors — `ruff check`
```

A plan acceptance item either **references** one or more `EC-<ALIAS>-<N>` IDs (the
goal is canonical; the item adds only the proving command) or is a **plan-internal**
item (no EC-ref — plan-local done conditions). This reuses the existing "each
acceptance criterion names the command that proves it" contract; the only change is
the item cites a **goal ID** instead of a reworded assertion.

**Reference grammar (hardened per CR — this is where fuzz could relocate):**
- An EC-ID counts as a reference **only in item-leading position** of a
  `## Acceptance Criteria` checklist item (`- [ ] EC-P1-1 — …`). A free-text prose
  mention ("NOTE: EC-P1-2 deferred", "we skipped EC-P1-2") does **not** count as
  coverage. Extraction is section- and position-scoped, never a global regex over
  the plan file.
- A reference to an EC-ID that does **not** exist in the anchored roadmap phase (a
  typo/dangling ref, e.g. `EC-P1-11`) is a `contract_bug`, not a silently-ignored
  plan-internal item.

### The decidable completeness check (replaces the fuzzy audit)

Mirrors the IF-gate `Produces` closeout precedent
(`closeout_validation.extract_plan_produces` vs closeout-reported `produced_if_gates`
→ `contract_bug` block): scrape the plan's declared `EC-<ALIAS>-<N>` references, load
the roadmap phase's declared EC-IDs, and block (`contract_bug`) if any roadmap EC-ID
for the phase is **not referenced** by ≥1 plan acceptance item. 1:many is fine (a
goal referenced by many items; an item referencing many goals). This is a set
membership check — no word-matching.

### Home: plan-time + preflight + CLOSEOUT (three points; NOT the frozen payload)

The `EmitPhaseCloseout` BAML **payload** is frozen (golden-hash + 5-harness
parity), so the check does not add a field to it. But the check itself runs in
**pure Python** at three points where roadmap + plan are already in hand:

- **Preflight** (`runner.py:3010`, already receives `roadmap`) — the plan-time gate.
- **Closeout** — **required, not optional** (CR: all three seats). Plans get edited
  *during* execution (retro-editing acceptance criteria is a known failure class),
  so a reference can vanish between preflight and closeout. `closeout_validation.py`
  is pure Python (the frozen thing is the BAML payload, not this validator) and
  `extract_plan_produces` already **re-reads the plan on disk at closeout**; the
  roadmap loads from the repo. So `check_goal_coverage` is called beside
  `validate_produced_gates` at closeout with **no BAML/frozen-contract change** —
  mirroring the IF-gate `Produces` precedent, which runs at closeout for exactly
  this mutation-window reason. (This corrects the first draft, which wrongly claimed
  CloseoutContext couldn't reach the roadmap.)
- **Plan-time `validate_plan_doc.py` check** — deferred to Increment 2 (that file
  lives in the parity-gated skill bundle). In Increment 1 the plan-time surface is
  the standalone CLI; the *enforced* gates are the preflight + closeout (runtime).

All stay **warn-default, opt-in block** via `PHASE_LOOP_ACCEPTANCE_ENFORCE`
(autonomy-first, unchanged).

### Opt-in per phase — untouched legacy is safe; *activating* IDs is a coordinated migration

A phase that declares `EC-<ALIAS>-<N>` IDs opts into enforcement; a legacy phase
with no EC-IDs keeps today's behavior (no new gate). **Untouched** legacy roadmaps
and their plans (including downstream repos) do not break.

But **activating** IDs on an existing roadmap is *not* a silent edit (CR codex):
adding IDs changes the roadmap bytes, and plans pin `roadmap_sha256`
(`discovery.plan_artifact_diagnostic` rejects a mismatch), so activation **stales
every affected plan** — which already requires a re-plan against the amended
roadmap. Therefore ID activation is a **coordinated roadmap+plan migration** (add
IDs and re-plan together), never a mid-flight roadmap edit under
`PHASE_LOOP_ACCEPTANCE_ENFORCE=block`. Also acknowledged: retiring the fuzzy audit
means legacy (un-migrated) roadmaps have **no** coverage checking until migrated — a
temporary regression, accepted because the fuzzy audit was proven undecidable and
often wrong.

## Increments (this is bigger than #211 — scoped as a decision gate)

This spans a grammar, a parser, a validator, 3 planner skills × 4 harnesses (behind
the CANON parity regen gate), a preflight, and migration. It will **dwarf** the
remaining backlog (#177/#202 are hours; this is the largest single initiative in the
cleanup). So it is cut into increments with a **go/no-go after Increment 1**.

### Increment 1 — the mechanism (bounded; NO skill-fleet edits) — the decision gate

Ships the full decidable capability on hand-authored fixtures, touching only runtime
code (not the parity-gated skill bundle):

- `roadmap_lint.py` — parse `EC-<ALIAS>-<N>` from `**Exit criteria**` items; add a
  reconciliation check (alias-scoped, unique, **never-reused (not contiguous)**,
  **all-or-none per phase**) modeled on `check_if_gates`. **API-safe (CR gemini):**
  keep `Phase.exit_criteria: list[str]` unchanged (downstream code iterates it as
  strings); add an **additive** accessor `Phase.exit_criteria_ids` /
  `parsed_exit_criteria` returning the `(id, text)` pairs. Do not change the existing
  field's type.
- A new `goal_coverage.py` module — `extract_plan_goal_refs(plan)` (scrape
  `EC-<ALIAS>-<N>` refs **only from item-leading position in the `## Acceptance
  Criteria` section**, never a global regex) + `check_goal_coverage(repo, plan,
  roadmap)` → the decidable completeness result: every declared EC-ID referenced;
  any dangling ref (unknown ID) → `contract_bug`. Opt-in: a phase with no EC-IDs →
  `not_applicable` (no gate).
- Wire it into (i) the existing preflight (**replacing** the fuzzy
  `run_acceptance_coverage_audit` call at `runner.py:3010`), (ii) a **closeout**
  re-check beside `validate_produced_gates` in `closeout_validation.py` (pure Python,
  plan-on-disk + repo-loaded roadmap; no BAML change), and (iii) a standalone CLI.
- **Retire** `acceptance_coverage_audit.py` (the fuzzy tool) and abandon the
  unmerged `feat/acceptance-coverage-audit-211` branch — this redesign supersedes it.
  (Verified: no skill references the fuzzy audit surface, so retiring it forces no
  skill edit into I1.)
- Tests: all on fixtures — EC-ID parse + reconciliation; **mixed-mode phase →
  `roadmap_lint` error**; every-ID-referenced → clean; a dropped EC-ID →
  `contract_bug`; a **dangling ref** → `contract_bug`; a **prose-mention (not
  item-leading) does NOT count** → still a gap; 1:many (one ID/two items; one
  item/two IDs) → clean; legacy phase (no IDs) → not_applicable; **post-preflight
  reference deletion caught at the closeout re-check**; preflight warn-default vs
  `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`; `Phase.exit_criteria` still `list[str]`
  (API-compat regression).

**Decision gate:** after I1, the user greenlights (or not) the fleet-wide skill
change before any parity-gated edits. I1 delivers real value alone (dropped-goal
detection, decidably) without the highest-risk surface.

### Increment 2+ — skills emit/reference by default, then migrate (only on GO)

- roadmap-builder skill (×4 harness `skills-src/`) — emit `EC-<ALIAS>-<N>` on each
  exit-criterion; document the ID convention. Regen past CANON parity.
- plan-phase + plan-detailed skills (×4) — author acceptance items as **EC-ID
  references + proving command**, not restatements; update the templates + rigor
  rules; `validate_plan_doc.py` gains the reference check.
- Migration — opt-in per roadmap; a helper to add EC-IDs to an existing roadmap;
  migrate in-repo `specs/phase-plans-v*.md` deliberately (not a blind sweep). Legacy
  roadmaps keep working until migrated.

## Open product decisions (for the plan review / user)

1. **Coarse goals:** some exit-criteria genuinely bundle several checks. Allowed
   (referenced once, adequacy human-reviewed)? Or must roadmap-builder decompose
   them into per-check EC-IDs at authoring? (Recommendation: allow, with the coverage
   check completeness-only; adequacy is CR/#91.)
2. **Enforcement default:** warn-default + opt-in block (consistent with the rest of
   the phase-loop) — confirm.
3. **CLI naming:** repurpose `acceptance-coverage-audit` vs add `goal-coverage-audit`.

## Documentation impact

- Increment 1: `CHANGELOG.md` (the decidable goal-coverage check replaces the fuzzy
  audit); a short `EC-<ALIAS>-<N>` grammar note (where the IF-gate scheme is
  documented). No `_contract_docs` freeze touched.
- Increment 2: the roadmap-template + planner-skill docs; `roadmap-template.md`.

## Verification (Increment 1)

```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python3 -m pytest tests/test_goal_coverage.py tests/test_phase_loop_roadmap_validate.py -q
# fixtures: dropped EC-ID -> contract_bug; all referenced -> clean; 1:many -> clean;
# legacy roadmap (no EC-IDs) -> not_applicable; preflight warn vs block.
```

## Acceptance criteria (Increment 1)

- [ ] `roadmap_lint` parses `EC-<ALIAS>-<N>` and reconciles them (alias-scoped,
  unique, never-reused, **all-or-none per phase → mixed-mode is a `roadmap_lint`
  error**); `Phase.exit_criteria` stays `list[str]` (API-compat), IDs via an additive
  accessor.
- [ ] `check_goal_coverage` blocks (`contract_bug`) when a declared roadmap EC-ID is
  unreferenced, or on a **dangling** ref, or when a reference is only a **prose
  mention** (not an item-leading acceptance line); passes on all-referenced (incl.
  1:many); returns `not_applicable` for a phase with no EC-IDs.
- [ ] The check runs at the phase-loop **preflight AND closeout** (pure Python, no
  BAML change) + a standalone CLI, warn-default / opt-in block via
  `PHASE_LOOP_ACCEPTANCE_ENFORCE`, never `human_required` — replacing the fuzzy
  `run_acceptance_coverage_audit` call. A post-preflight reference deletion is caught
  at closeout.
- [ ] The fuzzy `acceptance_coverage_audit.py` is removed and the redesign explicitly
  supersedes the unmerged `feat/acceptance-coverage-audit-211` branch.
- [ ] No frozen contract changed (roadmap format additive; `EmitPhaseCloseout` BAML
  untouched); full non-dotfiles suite green.

## Plan-review outcome (cross-vendor)

codex + gemini + Fable reviewed this plan. **Unanimous:** the redesign genuinely
escapes the undecidability trap — the completeness check is decidable set membership,
a "massive improvement over semantic diffs," no word-matching. All three flagged the
same hardenings, now folded in above: (1) all-or-none activation (mixed-mode hole),
(2) closeout re-check for the edit-during-execution window (and the first draft's
"can't reach roadmap at closeout" reasoning was wrong — corrected), (3) reference
grammar (item-leading only, dangling → block), (4) never-renumber ID stability,
(5) additive `Phase.exit_criteria` accessor (API-compat), (6) activation = coordinated
roadmap+plan migration, (7) I1 = CLI+preflight+closeout (runtime); `validate_plan_doc.py`
is I2.

## Scale statement & go/no-go

Increment 1 is a bounded runtime change (~1 parser extension + 1 new module + 1
preflight rewire + fixtures) delivering **decidable dropped-goal detection**.
Increment 2+ is a **fleet-wide skill change** (3 skills × 4 harnesses + CANON regen +
in-repo roadmap migration) that is the single largest item in the cleanup backlog —
larger than #177 + #202 + the org-rename sweep combined. **Recommendation:** land
Increment 1, then explicitly decide whether to commit to Increment 2+ now or after
the smaller concrete items (#177, #202) ship. This plan is the scoping deliverable;
implementation waits on approval.
