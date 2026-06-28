# agent-harness — Model Routing & Governed Review (model-routing-v1) — Phase Plan v2

> How to use this document: save to `specs/phase-plans-v2.md`, then run `/claude-plan-phase <ALIAS>` to produce the lane-level plan for each phase (→ `plans/phase-plan-v2-<alias>.md`), then `/claude-execute-phase <alias>` to build it.

---

## Context

A research review of model-tier mapping for governed agent pipelines concluded what serious agent systems already do in public: **specialize the role, route by task and risk, fail over within a class, and verify** — not "switch everything to the smartest model." This roadmap incorporates that into the harness.

Current state: `profiles.py` maps each *executor* (codex/claude/gemini/…) to a single heavy model with a blunt action→effort map (`plan`/`review`=high, `execute`=medium). There is no axis to say "plan with the planner-class model, implement with the implementer-class model, do bounded worker tasks with the worker-class model" *within* an executor. Model selection is also difficulty-blind.

Thesis: add a **vendor-agnostic tier layer** (`planner` / `implementer` / `worker`) resolved to concrete models per executor, raise planning effort to `max` (auto-clamped to each provider's ceiling), and add an **opt-in governed mode** in which planning and pre-merge are reviewed by a 3-harness panel (the `advisor-panel` skill: Codex/GPT-5.5 + Gemini 3.1 Pro + native Claude, at max) with bounded review→fix→re-review and an escalation ladder.

Hard constraint carried from the rigor-v1 work: **autonomy stays the default.** The panel and the governed review loop are opt-in; the default autonomous path remains warn-only and never adds `human_required`. The two are distinct operating modes selected per run/risk, not a global flip.

---

## Assumptions (fail-loud if wrong)

1. `resolve_execution_policy()` (`profiles.py`) is the single seam that resolves model + effort per action/lane; a `tier` axis can hook there.
2. `normalize_provider_effort` already clamps a requested effort to each provider's supported set, so requesting `max` is safe (claude→max, gemini→high, codex→its ceiling).
3. The `advisor-panel` skill is available as the 3-harness panel and runs each member at maximum reasoning.
4. The rigor-v1 closeout-validator hook + `PHASE_LOOP_REVIEW` warn/block severity model can host the governed review gate (block = must-fix, nit = warn).
5. Harness authentication/availability is detectable (the `codex-cli-runner` / `gemini-cli-runner` skills already fail-closed on auth).

## Non-Goals

- **No change to the autonomous default.** Governed mode and the panel are opt-in; the autonomous path stays warn-only and never raises `human_required`.
- **No unbounded review loops.** "Until mergeable without nits" is capped (default 3 rounds) and escalates on non-convergence — it never spins forever.
- **No new providers or executors.** Tiering happens across the models already wired in `profiles.py` / `capability_registry.py`.
- **Gemini is not the max-effort planner of record** (its effort ceiling is `high`); it serves as a panel member and multimodal/grounding role, not the authoritative max-effort planner.
- No dependence on raw chain-of-thought; route on reasoning-effort controls and observable behavior.
- No runtime difficulty auto-router; difficulty judgment stays with the planner (per the rigor-v1 `## Execution Policy` mechanism).

---

## Cross-Cutting Principles

1. **Autonomy-first by default.** Governed gates are opt-in; the default path is unattended, warn-only, no `human_required`. See the rigor-v1 guardrail.
2. **Tier is policy; executor is availability.** Roles resolve to a `tier`; the concrete model is `(tier, executor) → model`. Failover prefers same-tier cross-vendor before any tier downgrade.
3. **Reviewer ≠ author.** A panel reviewing an artifact must differ from its author in vendor *and* class — no same-model self-review.
4. **The panel is a boundary gate, never an inner loop.** It runs at planning and pre-merge only — three frontier models at max is too costly for per-closeout use.
5. **Bound everything.** Review rounds are capped; the failure escalation ladder is `implementer → planner → advisor/panel → human`, each step explicit and logged.
6. **Declarative, layered policy.** A repo-level `model_policy` holds the defaults; plan `## Execution Policy` and CLI `--model/--effort` override it. No scattered `if executor ==` branches.
7. **Single-writer foundation.** Only P1 edits `profiles.py` / `models.py`; later phases consume the frozen resolution interface.

---

## Phase Dependency DAG

```
  P1  Tier layer + policy + effort map
   │
   ├───────────────┐
   ▼               ▼
  P2  Governed     P4  Route logging
  mode + panel     (parallel after P1)
   │               │
   ▼               │
  P3  Impl review  │
  loop + ladder    │
   │               │
   └───────┬───────┘
           ▼
  P5  CI invariants + docs
```

---

## Top Interface-Freeze Gates

These gates are the narrowest contracts that unblock downstream phases. `/claude-plan-phase` concretizes each (exact signature/schema) when it plans the owning phase.

1. **IF-0-P1-1** — Tier-resolution interface: a `tier` field (`planner` | `implementer` | `worker`) on the execution-policy rule, and a resolver that maps `(tier, executor)` to a concrete model (claude→opus/sonnet/haiku, codex→gpt planner/impl/worker, gemini→pro/flash/flash-lite), composing with effort clamping.
2. **IF-0-P1-2** — Repo-level `model_policy` schema: per-executor tier→model maps, the action→effort defaults (roadmap/plan=`max`, execute/repair=`medium`, review=`high`), escalation thresholds, and the default run mode (`autonomous`). Precedence: CLI > plan `## Execution Policy` > `model_policy` > registry defaults.
3. **IF-0-P2-1** — Governed panel-review gate contract: the gate invocation (author artifact + reviewer-pool selection), finding severity (`block` vs `nit`, reusing the review-gate model), the reviewer-≠-author rule, and the availability-degradation contract (3 harnesses → 1 harness × 3 distinct-lens reviews with a recorded reduced-confidence flag).

---

## Phases

### Phase 1 — Tier Layer, Policy & Effort Map (P1)

**Objective**
Add the vendor-agnostic `tier` axis, a repo-level `model_policy`, and the planning-at-max effort map — landed back-compatibly so that with no policy present, resolution is unchanged.

**Exit criteria**
- [ ] A `tier` field (`planner`/`implementer`/`worker`) exists on the execution-policy rule and `resolve_execution_policy()` maps `(tier, executor)` to a concrete model; a unit test resolves `(planner, claude)`→`claude-opus-4-8` and `(implementer, claude)`→`claude-sonnet-4-6`.
- [ ] A repo-level `model_policy` loads and is overridden by plan `## Execution Policy` and CLI `--model/--effort`; a precedence test proves CLI > plan > policy > defaults.
- [ ] Effort-by-action defaults set roadmap=`max`, plan=`max` (covers plan-phase + plan-detailed), execute=`medium`, repair=`medium`, review=`high`; a test shows `normalize_provider_effort` clamps a `max` planning request to `high` for the gemini executor.
- [ ] With no `model_policy` present, model + effort resolution is byte-for-byte unchanged: the existing `profiles`/`discovery` tests pass unmodified.

**Scope notes**
- Decompose into 3 lanes owning disjoint files: (a) the `tier` axis + `(tier, executor)` resolver in `profiles.py`/`models.py` — **single writer** of those two files for the whole roadmap; (b) the `model_policy` loader + precedence resolution; (c) the effort-by-action defaults + provider clamping tests. Lane (a) publishes IF-0-P1-1 first so (b)/(c) compile against it.
- Single-writer files: `profiles.py`, `models.py` (lane a).

**Non-goals**
- No governed-mode behavior, no panel — P1 only establishes resolution + policy.

**Key files**
- phase-loop-runtime/src/phase_loop_runtime/profiles.py
- phase-loop-runtime/src/phase_loop_runtime/models.py
- phase-loop-runtime/src/phase_loop_runtime/discovery.py
- phase-loop-runtime/src/phase_loop_runtime/capability_registry.py

**Depends on**
- (none)

**Produces**
- IF-0-P1-1
- IF-0-P1-2

---

### Phase 2 — Governed Mode & Planning Panel Gate (P2)

**Objective**
Add an opt-in governed run mode; in governed mode, route authored plans/roadmaps through the 3-harness `advisor-panel` at max, classify findings, incorporate, and bound the re-review — with autonomous behavior untouched.

**Exit criteria**
- [ ] A run-mode selector exists (`autonomous` default | `governed` opt-in via flag/env); a regression test proves an autonomous run invokes no panel and adds no `human_required`.
- [ ] In governed mode, a planning-stage gate runs the `advisor-panel` skill (3 harnesses at max), records each finding as `block` or `nit` (reusing the review-gate severity), and blocks plan promotion only while unresolved `block` findings remain.
- [ ] The reviewer pool is disjoint from the author in vendor and class; a test asserts a sonnet/claude-authored plan is not reviewed solely by a claude reviewer.
- [ ] Availability fallback: when fewer than 3 harnesses are authenticated, the gate degrades to 1 harness × 3 distinct-lens reviews (correctness / security / simplicity) and records a reduced-confidence flag; a test exercises the degraded path.

**Scope notes**
- Decompose into 3 lanes owning disjoint files: (a) the run-mode selector + the autonomous-path regression guard; (b) the planning panel gate + severity classification, registered through the rigor-v1 review hook; (c) harness availability detection + the degradation policy. Disjoint files; lane (b) consumes IF-0-P1-1/IF-0-P1-2.

**Non-goals**
- No implementation-stage review (that is P3); P2 covers the planning boundary only.

**Key files**
- phase-loop-runtime/src/phase_loop_runtime/runner.py
- phase-loop-runtime/src/phase_loop_runtime/closeout_validators.py
- phase-loop-runtime/src/phase_loop_runtime/capability_registry.py
- phase-loop-skills/plan-phase/_overrides/claude/SKILL.md

**Depends on**
- P1

**Produces**
- IF-0-P2-1

---

### Phase 3 — Implementation Review Loop & Escalation Ladder (P3)

**Objective**
Implement at the implementer (sonnet) tier; in governed mode run a bounded pre-merge review→fix→re-review loop to zero `block` findings; escalate on failure via `implementer → planner → advisor/panel → human`.

**Exit criteria**
- [ ] Implementation dispatches at the `implementer` tier by default (resolved via IF-0-P1-1); a test asserts `execute`→implementer.
- [ ] The escalation ladder is enforced: on `failed_tests ≥ 2` or `patch_retries ≥ 2` the tier escalates implementer→planner; if the planner tier still fails the configured threshold, the advisor/panel is invoked; a test drives each transition.
- [ ] The governed pre-merge loop runs panel review → fix → re-review, capped at N rounds (default 3); zero `block` findings = mergeable (nits recorded, non-gating); non-convergence escalates to a human/adjudicator and never loops unbounded; a test covers the cap and the escalation.
- [ ] Autonomous mode is unaffected — no panel, no `human_required` (regression test).

**Scope notes**
- Decompose into 2 lanes owning disjoint files: (a) implementer-tier dispatch + the failure escalation ladder in the runner; (b) the governed pre-merge review loop with bounded rounds, consuming IF-0-P2-1. Disjoint files.

**Non-goals**
- No new test framework; reuse the repo's verification/closeout gates.

**Key files**
- phase-loop-runtime/src/phase_loop_runtime/runner.py
- phase-loop-runtime/src/phase_loop_runtime/closeout_validators.py
- phase-loop-skills/execute-phase/_overrides/claude/SKILL.md

**Depends on**
- P2

**Produces**
- (none)

---

### Phase 4 — Route Logging & Observability (P4)

**Objective**
Record every routing decision into the event ledger so cost, latency, failure, and escalation are auditable, and surface panel verdicts in the run-end summary.

**Exit criteria**
- [ ] Every dispatch logs `tier`, `concrete_model`, `effort`, and `route_reason` (and `escalated_from`/`escalated_to` when present) into the event ledger; a test asserts the fields appear on a dispatched event.
- [ ] Panel verdicts and any reduced-confidence flag are recorded and surfaced through the rigor-v1 run-end findings summary; a test asserts a governed-run summary names the panel outcome.
- [ ] Route logs are metadata-only (no secrets, no raw artifact bodies); a test asserts redaction.

**Scope notes**
- Single lane (one coherent observability seam): it owns the new logging fields on the dispatch/closeout path and the run-end-summary extension, partitioned away from P2/P3's gate logic so the files stay disjoint.

**Non-goals**
- No dashboards or external exporters; ledger fields + the existing summary only.

**Key files**
- phase-loop-runtime/src/phase_loop_runtime/runner.py
- phase-loop-runtime/src/phase_loop_runtime/review_summary.py
- phase-loop-runtime/src/phase_loop_runtime/models.py

**Depends on**
- P1

**Produces**
- (none)

---

### Phase 5 — CI Routing Invariants & Docs (P5)

**Objective**
Lock the policy with invariant tests and document the two operating modes — the terminal synthesis phase.

**Exit criteria**
- [ ] Routing-invariant tests pass: planning never resolves below its requested ceiling; the `worker` tier never authors a final patch; a governed merge requires a recorded panel pass; the reviewer pool is disjoint from the author; gemini is never the max-effort planner of record.
- [ ] `README.md` and `CHANGELOG.md` document the autonomous-vs-governed modes, the tier layer, `model_policy`, and the panel gate.
- [ ] `phase-loop validate-roadmap specs/phase-plans-v2.md` passes and the full standalone suite is green.

**Scope notes**
- Single lane (a coordinated cross-cutting invariant suite + docs sweep that must land atomically to stay consistent); sequenced after P2/P3/P4 so it tests and documents gates that already exist.

**Non-goals**
- No new enforcement; P5 only verifies and documents what P1–P4 built.

**Key files**
- phase-loop-runtime/tests/
- README.md
- CHANGELOG.md

**Depends on**
- P2
- P3
- P4

**Produces**
- (none)

---

## Execution Notes

- **Planning**: `/claude-plan-phase <ALIAS>` for each phase. `P1` is the root; `P2` and `P4` can be planned concurrently once `P1`'s interface gates are frozen.
- **Execution**: `/claude-execute-phase <alias>` after each plan is approved. `P4` (route logging) executes in parallel after `P1`; `P2 → P3` is the governed-review spine.
- **Critical path**: `P1 → P2 → P3 → P5` — wall-clock minimum. `P4` is off the critical path (parallel after `P1`).
- **Parallel branches**: `P4` runs alongside `P2`/`P3`; its panel-verdict logging fields are additive and wire up when `P2`/`P3` emit them.
- **Single-writer files across phases**:
  - `phase-loop-runtime/src/phase_loop_runtime/profiles.py` — **P1 only**.
  - `phase-loop-runtime/src/phase_loop_runtime/models.py` — **P1 only** (P4 adds only new ledger fields in a disjoint section; sequence P4's `models.py` touch after P1 merges).
  - `phase-loop-runtime/src/phase_loop_runtime/runner.py` and `closeout_validators.py` — touched by P2, P3, P4; assign one integrator lane or sequence the merges (P2 → P3 → P4) to avoid edit collisions.

---

## Acceptance Criteria

- [ ] **Autonomy preserved by default:** an unattended run resolves implementer-tier execution and planner-tier `max` planning, invokes no panel, and adds no `human_required` — existing suite plus the new regression are green.
- [ ] **Governed opt-in works:** with the governed flag, planning and pre-merge are panel-gated; `block` findings prevent merge, nits do not; the review loop is bounded and non-convergence escalates rather than looping.
- [ ] **Tier is vendor-agnostic policy:** `(tier, executor) → model` resolves for claude/codex/gemini, and the reviewer pool is enforced disjoint from the author.
- [ ] **Effort map:** roadmap / plan-phase / plan-detailed resolve to `max` (clamped per provider); execute resolves to `medium`.
- [ ] **Observability:** route decisions and panel verdicts appear in the event ledger and the run-end summary, metadata-only.
- [ ] `phase-loop validate-roadmap specs/phase-plans-v2.md` passes and the full standalone suite is green.

---

## Verification

```bash
# Roadmap lints clean
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v2.md

# Tier resolution, policy precedence, effort clamping (after P1)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/ -k "tier or policy or effort or routing" -q

# Governed mode + panel gate + escalation (after P2, P3)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/ -k "governed or panel or escalation" -q

# Route logging + run-end panel verdicts (after P4)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/ -k "route_log or review_summary" -q

# Full standalone suite (after P5)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest -q
```
