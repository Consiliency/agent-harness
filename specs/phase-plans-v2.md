# agent-harness — Model Routing & Governed Review (model-routing-v1) — Phase Plan v2

> How to use this document: save to `specs/phase-plans-v2.md`, then run `/claude-plan-phase <ALIAS>` to produce the lane-level plan for each phase (→ `plans/phase-plan-v2-<alias>.md`), then `/claude-execute-phase <alias>` to build it.

> **Revision r2** — reconciled against a 3-harness advisor panel (Codex/GPT-5.5, Gemini 3.1 Pro, repo-aware Claude) plus primary-source verification. The flagship fixes: separate the two orthogonal axes (model_policy vs run_mode), make the autonomous/governed boundary a real pre-invocation gate (not a severity downgrade), serialize P4 behind P3 (the cross-phase dirty start-gate would mechanically block it), and require an explicit per-provider effort-clamp policy (the runtime raises on an unsupported effort — it does **not** auto-clamp).

---

## Context

A research review of model-tier mapping for governed agent pipelines concluded what serious agent systems already do: **specialize the role, route by task and risk, fail over within a class, and verify** — not "switch everything to the smartest model." This roadmap incorporates that into the harness.

Current state: `profiles.py` maps each *executor* (codex/claude/gemini/…) to a single heavy model with a blunt action→effort map (`plan`/`review`=high, `execute`=medium, `profiles.py:24`). Model selection has no role axis (`ExecutionPolicyRule` has no such field, `models.py:576`) and is difficulty-blind.

**Two orthogonal axes — keep them separate (the panel's flagship correction):**
- **`model_policy`** (a *what-model* axis): a vendor-agnostic role layer (`planner`/`implementer`/`worker`) resolved to a concrete model per executor, plus an effort map. **This repo ships a default `model_policy`** (planning at `max`, execution at the implementer model). A downstream repo with *no* policy keeps today's resolution byte-for-byte — that empty-policy path is the back-compat guarantee, **not** this repo's shipped defaults.
- **`run_mode`** (a *how-governed* axis): `autonomous` (default) vs `governed` (opt-in). Autonomous is warn-only, invokes **no** panel, and never adds `human_required`. Governed adds panel review at planning + pre-merge with a bounded loop.

These are independent: this repo's default is **autonomous run_mode over the tiered model_policy**. "Autonomous default" means the run_mode, not the absence of a policy.

Thesis: add the role layer + `model_policy`, raise planning effort to `max` (with an explicit per-provider clamp so sub-max providers resolve to their ceiling instead of raising), and add the opt-in governed mode that reuses the rigor-v1 `ReviewFinding`/severity *vocabulary* — but on seams that fire at the right time and respect the run_mode boundary.

---

## Assumptions (fail-loud if wrong)

1. `resolve_execution_policy()` (`profiles.py`, on the live dispatch path at `runner.py:2468`) is the single seam that resolves model + effort per action/lane; a role axis hooks there.
2. **Effort does NOT auto-clamp.** `normalize_provider_effort` (`profiles.py:84`) *raises* on an unsupported effort unless the rule sets `unsupported_policy_behavior=fallback` (the provider `effort_map`, e.g. gemini `max→high` at `capability_registry.py:412`, then applies) or `inherit_default`. So requesting `max` for a sub-max provider requires the shipped policy to set that clamp explicitly.
3. The `ReviewFinding`/`PHASE_LOOP_REVIEW` severity model (rigor-v1, `closeout_validators.py`) is reusable as a *finding vocabulary* (`block`/`nit`, never `human_required`), but its `_VALIDATORS` registry fires at **closeout** on **every** closeout gated only by env severity — it is **not** run_mode-aware and is the wrong host for a planning-stage or autonomous-skipping gate.
4. The runner is a deterministic Python orchestrator with **no native "invoke a skill" primitive**; a 3-harness panel means spawning the subscription CLI legs (codex/agy/native-claude) as child processes, each with known non-interactive failure modes (`capability_registry.py:137-143`; agy emits no structured JSON). The panel must be a *named, fail-closed interface*, not an inline assumption.
5. The cross-phase dirty start-gate (`runner.py:915`) will **refuse** to start a phase whose paths overlap an in-flight phase's dirty lien — so phases sharing a hot file cannot truly run in parallel.

## Non-Goals

- **No change to the autonomous run_mode behavior.** Governed mode and the panel are opt-in; the autonomous path stays warn-only, invokes no panel, and never raises `human_required`.
- **No unbounded review loops** and **no synchronous human handoff.** "Until mergeable without nits" is capped (default 3 rounds); the terminal is a non-human `review_gate_block` + halt + run-end surfacing for the between-batch human (cadence via `--max-phases`), never a blocking wait for a person.
- **No new providers or executors;** role-tiering uses the models already in `capability_registry.py`.
- **Gemini is not the max-effort planner of record** (ceiling `high`); it serves as a panel member / multimodal role.
- No dependence on raw chain-of-thought; route on effort controls and observable behavior.

---

## Cross-Cutting Principles

1. **Two axes, separated.** `model_policy` (what model) and `run_mode` (how governed) are independent. Back-compat is the *empty-policy* path; this repo's shipped defaults intentionally differ and migrate their own baseline tests.
2. **Autonomy-first by default.** Default `run_mode=autonomous`: warn-only, no panel invocation, no `human_required`. The boundary is enforced by short-circuiting **before** any panel process is spawned — not by downgrading a finding's severity after the fact.
3. **Role is policy; executor is availability.** Roles resolve to a `model_class`; the concrete model is `(model_class, executor) → model`. Failover prefers same-class cross-vendor before any downgrade.
4. **Reviewer ≠ author**, in vendor *and* class. If the only authed reviewer vendor equals the author's (or zero are authed), the governed gate degrades to **autonomous-warn (advisory, recorded)** — it never rubber-stamps a same-vendor self-review as a confidence pass.
5. **The panel is a fail-closed boundary gate, never an inner loop.** Planning + pre-merge only; a named panel-invoker interface with liveness preflight and per-leg failure handling.
6. **Bound everything; terminate non-human.** Review capped (default 3 rounds); the failure ladder is `implementer → planner → [governed: panel] → non-human review_gate_block + halt + run-end surfacing`. In autonomous mode the ladder stops at `planner → repairable non-human blocker` (no panel, no human).
7. **Single-writer foundation.** Only P1 edits `profiles.py`/`models.py`. `runner.py` + `closeout_validators.py` are touched by P2/P3/P4 and get **one integrator lane** with a strict merge sequence — the start-gate will otherwise block overlapping phases.
8. **Avoid the "tier" name.** Use `model_class` (`planner`/`implementer`/`worker`) — "tier" already denotes evidence-audit budgets (`--tier-2/--tier-3`) and the `tiering` policy tests, and would collide.

---

## Phase Dependency DAG

```
  P1  model_class layer + model_policy + effort map (+ per-provider clamp)
   │
   ▼
  P2  Governed run_mode + planning panel gate + panel-invoker interface
   │
   ▼
  P3  Implementation review loop + escalation ladder (non-human terminal)
   │
   ▼
  P4  Route logging & observability (panel verdicts in run-end summary)
   │
   ▼
  P5  CI invariants + contract-doc & skill-override updates
```

(P4 is serialized behind P3: it logs panel verdicts that only exist after P2/P3, and it shares the `runner.py` hot path — the start-gate would block a parallel P4. Only its `review_summary.py` lane is independent; see Execution Notes.)

---

## Top Interface-Freeze Gates

These gates are the narrowest contracts that unblock downstream phases. `/claude-plan-phase` concretizes each (exact signature/schema) when it plans the owning phase.

1. **IF-0-P1-1** — Role-resolution + clamp interface: a `model_class` field (`planner`/`implementer`/`worker`) on the execution-policy rule, a resolver mapping `(model_class, executor)` to a concrete model, and the **per-provider effort-clamp** wiring (the shipped policy sets `unsupported=fallback`/`inherit_default` so a `max` request resolves to a sub-max provider's ceiling via its `effort_map` instead of raising).
2. **IF-0-P1-2** — `model_policy` schema + precedence: per-executor class→model maps, the action→effort defaults (roadmap/plan=`max`, execute/repair=`medium`, review=`high`), and where the shipped defaults sit. Precedence: CLI > plan `## Execution Policy` > `model_policy` > registry defaults. The **empty-policy path** reproduces today's resolution (the back-compat contract); the shipped policy intentionally differs and owns its baseline-test migration.
3. **IF-0-P2-1** — Governed-gate contract: a `run_mode` field on the closeout/dispatch context, the **short-circuit-before-panel-invocation** rule for `run_mode != governed`, a **plan-stage seam** distinct from the closeout `_VALIDATORS` registry (reusing only the `ReviewFinding` `block`/`nit` vocabulary), the reviewer-≠-author + degradation rules (author-vendor-only and zero-authed both degrade to autonomous-warn), and the non-human escalation terminal (`review_gate_block` + halt + run-end surfacing).
4. **IF-0-P2-2** — Panel-invoker interface: how the Python runner spawns the 3 subscription CLI legs (codex/agy/native-claude), liveness preflight, per-leg timeout/empty/degraded handling, and fail-closed parse — so the panel is a named dependency, not an inline call.

---

## Phases

### Phase 1 — Role Layer, Policy, Effort Map & Clamp (P1)

**Objective**
Add the `model_class` axis, the repo-level `model_policy` (with planning at `max` and a per-provider effort clamp), and migrate the affected baseline tests — keeping the *empty-policy* resolution path byte-for-byte unchanged for downstream consumers.

**Exit criteria**
- [ ] A `model_class` field (`planner`/`implementer`/`worker`) exists on the execution-policy rule and `resolve_execution_policy()` maps `(model_class, executor)` to a concrete model; a test resolves `(planner, claude)`→`claude-opus-4-8` and `(implementer, claude)`→`claude-sonnet-4-6`.
- [ ] The shipped `model_policy` sets a per-provider effort clamp so `(plan, gemini)` at `max` resolves to `high` via the `effort_map` fallback; a test proves it resolves (not raises), **and** a test documents that without the clamp policy `normalize_provider_effort` raises on `max` for gemini.
- [ ] With **no** `model_policy` and **no** `model_class`, resolution is byte-for-byte identical to today — the empty-policy path; a test asserts an unchanged `(plan, codex)`→`(gpt-5.5, high)`.
- [ ] The shipped policy's intended changes (`plan` `high→max`; `execute` claude `opus@high → sonnet@medium`) are reflected by **migrating** the affected baseline assertions in the same lane (not left as "tests pass unmodified").
- [ ] Precedence holds: CLI `--model/--effort` > plan `## Execution Policy` > `model_policy` > registry defaults (test).

**Scope notes**
- Decompose into 3 lanes owning disjoint files: (a) the `model_class` axis + `(model_class, executor)` resolver + clamp in `profiles.py`/`models.py` — **single writer** of those two files for the whole roadmap; (b) the `model_policy` loader + precedence + empty-policy back-compat; (c) the effort-map defaults + the baseline-test migration. Lane (a) publishes IF-0-P1-1 first.
- Single-writer files: `profiles.py`, `models.py` (lane a).

**Non-goals**
- No governed-mode behavior, no panel — P1 only establishes resolution, policy, and clamp.

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

### Phase 2 — Governed Mode, Planning Gate & Panel Invoker (P2)

**Objective**
Add an opt-in `run_mode=governed`; build a plan-stage panel gate (distinct from the closeout registry) that short-circuits in autonomous mode before any panel process spawns; and freeze the panel-invoker interface.

**Exit criteria**
- [ ] A `run_mode` field exists on the closeout/dispatch context (default `autonomous`); a regression test proves an autonomous run makes **zero** panel CLI calls (asserted by a spawn counter / mock, not merely "no `human_required`").
- [ ] The **planning gate** runs only in governed mode, on a plan-stage seam separate from the closeout `_VALIDATORS` registry, invokes the panel-invoker (IF-0-P2-2), classifies findings `block`/`nit` (reusing the `ReviewFinding` vocabulary), and blocks plan promotion only while unresolved `block` findings remain.
- [ ] Reviewer-pool selection enforces vendor+class disjoint from the author; when only the author's vendor is authed, or zero reviewers are authed, the gate **degrades to autonomous-warn** (records an advisory finding, does not pass-as-reviewed) — tests cover both states.
- [ ] The panel-invoker spawns codex/agy/native-claude, preflights liveness, and flags per-leg `empty`/`degraded`/`timeout` so a verbose auth error is not mistaken for a real review (test the degraded-leg path).

**Scope notes**
- Decompose into 3 lanes owning disjoint files: (a) `run_mode` field + the autonomous short-circuit + the zero-panel-call regression guard (touches the shared `runner.py`/`closeout_validators.py` path — **integrator lane**, see Execution Notes); (b) the plan-stage gate seam + finding classification; (c) the panel-invoker interface + leg failure handling. Lanes (b)/(c) own new modules.

**Non-goals**
- No implementation-stage review (P3); P2 covers the planning boundary and the invoker only.

**Key files**
- phase-loop-runtime/src/phase_loop_runtime/runner.py
- phase-loop-runtime/src/phase_loop_runtime/closeout_validators.py
- phase-loop-runtime/src/phase_loop_runtime/capability_registry.py
- phase-loop-skills/plan-phase/_overrides/claude/SKILL.md

**Depends on**
- P1

**Produces**
- IF-0-P2-1
- IF-0-P2-2

---

### Phase 3 — Implementation Review Loop & Escalation Ladder (P3)

**Objective**
Dispatch implementation at the implementer (sonnet) class; in governed mode run a bounded pre-merge review→fix→re-review loop to zero `block` findings; terminate every failure path non-human.

**Exit criteria**
- [ ] Implementation dispatches at the `implementer` class by default (via IF-0-P1-1); a test asserts `execute`→implementer.
- [ ] The escalation ladder is enforced and mode-branched: on `failed_tests ≥ 2` or `patch_retries ≥ 2` the class escalates implementer→planner; in **governed** mode a still-failing planner tier invokes the panel; in **autonomous** mode it terminates as a repairable non-human blocker (no panel, no `human_required`). A test drives both branches.
- [ ] The governed pre-merge loop runs panel review → fix → re-review capped at N rounds (default 3); zero `block` findings = mergeable (nits recorded, non-gating); non-convergence (and panel-unavailable-while-failing) terminates as a non-human `review_gate_block` + halt, surfaced in the run-end summary — never an unbounded loop and never a synchronous human wait.
- [ ] Autonomous mode is unaffected — no panel, no `human_required` (regression test).

**Scope notes**
- Decompose into 2 lanes owning disjoint files: (a) implementer-class dispatch + the mode-branched escalation ladder (shared `runner.py` — **integrator lane**); (b) the governed pre-merge review loop consuming IF-0-P2-1/IF-0-P2-2.

**Non-goals**
- No new test framework; reuse the verification/closeout gates.

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
Record every routing decision into the event ledger and surface panel verdicts in the run-end summary — serialized behind P3 because it logs verdicts that only exist after P2/P3 and shares the `runner.py` hot path.

**Exit criteria**
- [ ] Every dispatch logs `model_class`, `concrete_model`, `effort`, and `route_reason` (and `escalated_from`/`escalated_to` when present) into the event ledger; a test asserts the fields appear on a dispatched event.
- [ ] Panel verdicts and any degraded/advisory-warn flag are recorded and surfaced through the rigor-v1 run-end summary (`review_summary.py`, already wired at `runner.py:4204`); a test asserts a governed-run summary names the panel outcome.
- [ ] Route logs are metadata-only (no secrets, no raw artifact bodies); a redaction test.

**Scope notes**
- Decompose into 2 lanes: (a) the `review_summary.py` extension for panel verdicts — the **only** lane independent enough to start early; (b) the dispatch-path logging fields, which join the `runner.py`/`models.py` **integrator lane** sequenced after P3. Disjoint files within the phase.

**Non-goals**
- No dashboards or external exporters; ledger fields + the existing summary only.

**Key files**
- phase-loop-runtime/src/phase_loop_runtime/review_summary.py
- phase-loop-runtime/src/phase_loop_runtime/runner.py
- phase-loop-runtime/src/phase_loop_runtime/models.py

**Depends on**
- P3

**Produces**
- (none)

---

### Phase 5 — CI Invariants, Contract Docs & Skill Overrides (P5)

**Objective**
Lock the policy with invariant tests and update the surfaces that actually govern behavior — the runtime contract docs and skill overrides, not just README/CHANGELOG.

**Exit criteria**
- [ ] Routing-invariant tests pass: the empty-policy path is unchanged; the `worker` class never authors a final patch; a governed merge requires a recorded panel pass (or an explicit advisory-warn degradation); the reviewer pool is vendor+class disjoint from the author; gemini is never the max-effort planner of record (enforced at dispatch selection, not only by the effort clamp); an autonomous run makes zero panel calls.
- [ ] The runtime **contract docs** (`_contract_docs/phase-loop/protocol.md`), the plan/execute **skill overrides**, README, and CHANGELOG document the two axes (`model_policy` vs `run_mode`), the role layer, the clamp requirement, and the governed gate.
- [ ] `phase-loop validate-roadmap specs/phase-plans-v2.md` passes and the full standalone suite is green.

**Scope notes**
- Single lane (a coordinated cross-cutting invariant suite + docs/contract/skill sweep that must land atomically to stay consistent); sequenced after P2/P3/P4 so it tests and documents gates that already exist.

**Non-goals**
- No new enforcement; P5 only verifies and documents what P1–P4 built.

**Key files**
- phase-loop-runtime/tests/
- phase-loop-runtime/src/phase_loop_runtime/_contract_docs/phase-loop/protocol.md
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

- **Planning**: `/claude-plan-phase <ALIAS>` for each phase. The spine is strictly serial — `P1 → P2 → P3 → P4 → P5` — because every later phase shares the `runner.py`/`closeout_validators.py` hot path and the cross-phase dirty start-gate (`runner.py:915`) would refuse overlapping in-flight phases.
- **Execution**: `/claude-execute-phase <alias>` after each plan is approved. The only genuinely parallel work is P4's `review_summary.py` lane, which can be drafted against the rigor-v1 summary while P2/P3 build the verdicts it renders.
- **Critical path**: `P1 → P2 → P3 → P4 → P5` — there is no parallel branch at the phase level (the r1 draft's P4-parallel claim was false; the panel verified the start-gate blocks it).
- **Single-writer / integrator-lane files across phases**:
  - `phase-loop-runtime/src/phase_loop_runtime/profiles.py`, `models.py` — **P1 only** (P4's `models.py` ledger fields land in a disjoint section, sequenced after P1).
  - `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `closeout_validators.py` — touched by P2, P3, P4: assign **one integrator lane** that owns these two files across the three phases, merged in strict P2→P3→P4 order, so the start-gate never sees two in-flight phases dirtying the same path.

---

## Acceptance Criteria

- [ ] **Autonomy preserved by default:** an unattended run (default `run_mode=autonomous`) resolves implementer-class execution and planner-class `max` planning over the shipped `model_policy`, makes **zero** panel CLI calls, and adds no `human_required` — proven by a spawn-counter regression plus the migrated baseline suite.
- [ ] **Empty-policy back-compat:** a checkout with no `model_policy` and no `model_class` resolves model + effort byte-for-byte as today.
- [ ] **Governed opt-in works:** with `run_mode=governed`, planning and pre-merge are panel-gated; `block` findings prevent merge, nits do not; the loop is bounded; non-convergence and panel-unavailability both terminate as a non-human `review_gate_block` surfaced in the run-end summary — never a human wait.
- [ ] **Effort clamp is real:** `(plan, gemini)` at `max` resolves to `high` via the configured fallback (and is documented to raise without it).
- [ ] **Independence is honest:** reviewer pool is vendor+class disjoint from the author; author-vendor-only and zero-authed both degrade to autonomous-warn, never a self-review pass.
- [ ] `phase-loop validate-roadmap specs/phase-plans-v2.md` passes and the full standalone suite is green.

---

## Verification

```bash
# Roadmap lints clean
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v2.md

# Role resolution, empty-policy back-compat, gemini max->high clamp (after P1)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/ -k "model_class or policy or effort or clamp or routing" -q

# Autonomous makes zero panel calls; governed gate + invoker degradation (after P2, P3)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/ -k "run_mode or governed or panel or escalation" -q

# Route logging + run-end panel verdicts (after P4)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/ -k "route_log or review_summary" -q

# Full standalone suite (after P5)
cd phase-loop-runtime && PYTHONPATH=src python -m pytest -q
```
