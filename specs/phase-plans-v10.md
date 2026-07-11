# Phase roadmap v10 — POST070FIX (post-0.7.0 gaps, refinements, bugs)

## Context
0.7.0 (CLEANSHIP) shipped. This roadmap closes the remaining backlog synthesized from three sources: the SKILLREFLECT digest of 30 code-verified skill reflections, the open agent-harness issue backlog, and the deferred REVIEWGOV review-ratification architecture — plus a newly-surfaced local/origin divergence gap (PUSHFLOW). It has been reconciled against a 4-vendor panel's consolidated fixes: the oversized REVGOV2 phase is split into three (POLICY / SANDBOX / UNATTEND), OPUX is dissolved into them, gp#74 is carved out as a cross-repo phase (GPGATE), and every file anchor is corrected to panel-verified origin/main ground truth. Built for maximum parallelism: five disjoint parallel-root phases + two dependent chains. Full findings in `plans/bigpicture-fix-plan-post-0.7.0-20260711.md`. Baseline: origin/main @ 6cdbbd3 (includes #167, which addresses #165 — already closed).

## Architecture North Star
```
 parallel roots (disjoint file sets)                       dependent chains
 ┌───────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ ┌────────┐   ┌──────────┐
 │ SKILLREF  │ │ PUSHFLOW │ │ POLICY │ │ SANDBOX│ │MANIFEST│   │ RUNCORE2 │
 │ skills-src│ │ cli-arg  │ │ review │ │ panel  │ │discovery│→ │ runner.py│
 │ +regen    │ │ +doctor  │ │ policy │ │ leg    │ │reconcile│  │ reconcile│
 │ +draft-PR │ │ +RELPIN  │ │ persist│ │ sandbox│ │ (manif- │  │ train    │
 │  protocol │ │          │ │        │ │        │ │  est)   │  │          │
 └───────────┘ └──────────┘ └───┬────┘ └────────┘ └──────────┘  └──────────┘
 SKILL gaps    local≠origin      │ POLICY consumers:
 +draft-PR     visibility        ├─► UNATTEND (W4 + C1 #146/#145)
 +skill-paths  (cli default,     └─► GPGATE   (gp#74, cross-repo soft-gate)
               ahead-alarm,
               RELEASE_PIN)   review/panel single-writer region partitioned
                              POLICY{governed_review,closeout_validators} |
                              SANDBOX{panel_invoker,advisor_board/composition}
```

## Assumptions (fail-loud if wrong)
1. origin/main @ 6cdbbd3 or later; skills ship from agent-harness `skills-src/<harness>/<skill>/` (neutral base = codex; regen → sync → parity-gated); editing shared prose means all 4 harness sources.
2. Closeout push already FIRES at `runner.py:8185` (`if closeout_mode == "push": resolve_closeout_push_target(...); _git(repo,"push",...)`), but the default closeout mode is `"manual"`, set at the CLI arg layer `cli.py:1229` (`closeout_mode=args.closeout_mode or "manual"`). PUSHFLOW flips the DEFAULT at that arg layer — it does NOT edit `runner.py` (RUNCORE2's single-writer region). If runner-path closeout semantics must change, that work serializes INTO RUNCORE2.
3. Release-dispatch concurrency (#146) is emitted at `runner.py:1374/1390` via `DispatchLock` (`dispatch_lock.py`), NOT `lease_store.py`. C1's fix is the caller-identity exclusion in `dispatch_lock.py` (the lock file already holds the PID). Any runner-side identity injection at the 1374/1390 call sites is a NON-GOAL for UNATTEND and is deferred to RUNCORE2 as a noted lane.
4. #165 is ALREADY CLOSED (task-message persistence, fixed by #167, verified by the orchestrator). MANIFEST does not re-verify or re-open it; if a residual surfaces mid-execution, fold it in fail-loud.
5. The autonomy-first gate posture exists (validators never set human_required; review_gate_block/warn). The ONE validator-adjacent path that sets `human_required=True` is `release_guard.py:41 to_blocker()`; W4 flips that path under an unattended consensus policy. POLICY/UNATTEND EXTEND the posture, they do not replace it.

## Non-Goals
- No new hard human_required gates (autonomy-first: warn default, block opt-in) — including W3/W4; W4 only substitutes consensus for the EXISTING `release_guard.py` human grant under an explicit unattended policy.
- No grok spawn_subagent fix (#154) — undeliverable via CLI 0.2.93; the tripwire watches; revisit on grok upgrade.
- No portal#208 reconciliation (portal/fleet-gateway owners) — tracked, out of scope.
- No version bump inside fix phases — a follow-on RELEASE (not in this roadmap) stages the next tag.
- No runner-side dispatch-identity injection in UNATTEND (deferred to RUNCORE2).
- #84 stays open (no repro) unless RUNCORE2 reproduces it.

## Cross-Cutting Principles
1. TWO single-writer regions, and no phase outside each region's owners may edit its files:
   - `{runner.py, reconcile.py}` — the MANIFEST→RUNCORE2 chain (reconcile owned by MANIFEST first, then runner+reconcile by RUNCORE2).
   - the review/panel cluster `{panel_invoker.py, governed_review.py, closeout_validators.py}` — PARTITIONED at file granularity between POLICY (`governed_review.py`, `closeout_validators.py`, `gate_posture.py`) and SANDBOX (`panel_invoker.py`, `advisor_board/composition.py`) so no file is touched by both; that partition is exactly what makes POLICY and SANDBOX safe parallel roots. UNATTEND/GPGATE keep off both regions (UNATTEND writes only `dispatch_lock.py` + `release_guard.py`).
   (Panel note: the 4-vendor reconciliation flagged that an earlier draft named a single 3-file region "owned by SANDBOX" — that was inconsistent with POLICY writing two of those files; the file-partition above resolves it.)
2. Verify against a freshly-fetched origin/main, never a possibly-stale working tree.
3. Fold in any new bug noticed mid-execution as a fix (standing rule).
4. Each phase emits a `.consiliency/changelog.d/CHANGELOG-<alias>.md` chunk (basename starts with CHANGELOG — docs-audit `**/CHANGELOG*` glob); a follow-on RELEASE assembles them.
5. CR = 4-vendor (grok-4.5 / gpt-5.6-sol / Gemini-3.1-pro / claude-**fable** — Fable seat is explicit `model: fable`, never inherited Opus); agy + grok review legs run READ-ONLY (grok `--tools read_file,grep,list_dir,search_tool`; agy on a staged copy — both are write-capable). Bare `Closes #N` for auto-close (qualified fleet form does NOT auto-close). Split-verdict: concrete-defects-fixed + peer-confirm = convergent; adjudicate out-of-scope findings.
6. Cross-repo work (GPGATE / gp#74) drops a plan into the target repo and coordinates its execution there; it is a soft-gate and never blocks the agent-harness phases.

## Top Interface-Freeze Gates
1. IF-0-PUSHFLOW-1 — the closeout-push contract. Names the call path (`runner.py:8185`, where push already fires) + the default site (`cli.py:1229`, flipped to push-by-default) + `--no-push`/no-remote fallback + the `commits_ahead_of_origin` threshold on worktree/closeout status.
2. IF-0-POLICY-1 — the `ratification_policy` as a STRICT typed schema (dataclass/pydantic field list: `required_vendors:int`, `required_lens_coverage:int`, `required_consensus`, `on_shortfall: escalate|proceed_degraded`), NOT prose. Consumed by UNATTEND + GPGATE.
3. IF-0-SANDBOX-1 — the per-vendor review-leg sandbox mechanism, frozen per vendor (staged-copy vs deny-list).
4. IF-0-UNATTEND-1 — W4's decision/audit-record schema (the durable record a consensus-substitutes-for-human grant writes).
5. IF-0-MANIFEST-1 — per-entry manifest validation result shape (one bad entry no longer invalidates the whole manifest).

## Phases

### Phase 1 — Skill-reflection refinements (SKILLREF)
**Objective**
Fold the recurring, code-verified skill-reflection learnings into the phase-loop authoring skills, home the draft-PR-early protocol wording here (to avoid a skill-source collision with PUSHFLOW), then clear the digested reflection cache for a fresh 0.7.0 start.
**Exit criteria**
- [ ] roadmap-builder SKILL.md carries a "Validator Format Contract" block (alias `[A-Za-z0-9]+`; no decoration after `(ALIAS)`; each `**Field**` on its own line; lists bulleted; lane hint contains literal "decompose into N lanes"/"Single lane"; malformed heading cascades → fix heading first).
- [ ] roadmap-builder + plan-phase + plan-detailed + execute-phase lead with the `phase_loop_runtime.skill_paths` resolver; `handoff_path.py` demoted to fallback.
- [ ] skip-Explore-when-context-in-session + proportionality carve-out present in plan-phase + plan-detailed; multi-roadmap alias/create-mode note in roadmap-builder.
- [ ] execute-phase SKILL sources carry the draft-PR-early protocol: push branch + open a DRAFT PR on the first commit of a phase (re-homed here from PUSHFLOW so only ONE phase edits the execute-phase skill).
- [ ] all 4 harness sources edited, `regenerate_skills_bundle.py` + `sync_skills_bundle.py` run, `test_skills_canon_parity.py` green.
- [ ] `~/.codex/skills/*/reflections/` cleared (after the above lands) with a one-line note; full suite + guards green.
**Scope notes**
Decompose into 3 lanes: (a) roadmap-builder format-contract + multi-roadmap note; (b) skill-paths resolver + draft-PR-early protocol wording across all 4 execute-phase/authoring skills; (c) skip-Explore/proportionality + regen + cache-clear. Fully disjoint from runtime code — a parallel root. This phase OWNS every execute-phase SKILL-source edit in the roadmap, so PUSHFLOW stays a clean git-plumbing root (panel fix #5, option b).
**Non-goals**
No runtime code; no version bump.
**Key files**
- `skills-src/{claude,codex,gemini,opencode}/*/SKILL.md`
- `phase-loop-runtime/scripts/regenerate_skills_bundle.py`
- `scripts/sync_skills_bundle.py`
- `~/.codex/skills/*/reflections/`
**Depends on**
- (none)
**Produces**
- (none)

### Phase 2 — Push-after-merge visibility (PUSHFLOW)
**Objective**
Stop local branches diverging 70–100 commits ahead of origin: make push-on-closeout the DEFAULT by flipping the CLI arg-layer default (not by touching the runner push path), surface an ahead-of-origin signal, and add a doctor check that a pinned agent clone is not behind RELEASE_PIN.
**Exit criteria**
- [ ] closeout pushes by default: the CLI arg-layer default `closeout_mode` flips from `"manual"` to a push-capable mode at `cli.py:1229`; `--no-push` flag + graceful no-remote fallback; test proves push fires (via the existing `runner.py:8185` path) and `--no-push` suppresses it. NO edit to `runner.py`.
- [ ] `commits_ahead_of_origin: N` mirrors `main_behind` in worktree/closeout status + `phase-loop doctor`; WARN default, soft-block above a threshold (opt-in, never human_required).
- [ ] `phase-loop doctor` warns when the pinned agent clone (`~/.local/share/agent-harness`) is behind `RELEASE_PIN`; the fix + a documented release-step pin bump land (the live gap where clones sat at 0.6.0 under RELEASE_PIN=v0.7.0). WARN, never blocking.
- [ ] full suite + guards green.
**Scope notes**
Decompose into 3 lanes: (a) closeout-push-default at the cli.py arg layer + `--no-push` flag + no-remote fallback (`cli.py`, `git_topology.py`); (b) ahead-of-origin signal (`worktree_index.py`, `doctor*.py`); (c) RELEASE_PIN-staleness doctor check + release-step pin-bump doc. Git-plumbing + doctor files, disjoint from `runner.py` — a parallel root. Single-writer honesty: the push already fires in `runner.py:8185`; this phase must NOT edit `runner.py`, it only changes the default at `cli.py:1229`. No execute-phase SKILL edits here (the draft-PR-early wording is homed in SKILLREF).
**Non-goals**
No change to `--closeout-mode` semantics beyond the default value; no auto-merge; no `runner.py` closeout-path edits (RUNCORE2 owns that region).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/git_topology.py`
- `phase-loop-runtime/src/phase_loop_runtime/worktree_index.py`
- `phase-loop-runtime/src/phase_loop_runtime/doctor*.py`
**Depends on**
- (none)
**Produces**
- IF-0-PUSHFLOW-1

### Phase 3 — Ratification policy + review-finding persistence (POLICY)
**Objective**
Deliver the parameterized, typed ratification policy (REVIEWGOV W3) as the shape UNATTEND + GPGATE consume, absorb the #88 SHA-bound gate, and re-home #80 (review-finding-text persistence) here — it lives in the review-policy file cluster.
**Exit criteria**
- [ ] `ratification_policy` per gate (plan-ratify/design-ratify/pre-merge-CR/release-dispatch) is a STRICT typed schema — `required_vendors:int`, `required_lens_coverage:int`, `required_consensus`, `on_shortfall: escalate|proceed_degraded` — wired through `gate_posture`/`closeout_validators` posture with `BoardIndependence`/`lens_coverage`; extends (not replaces) the autonomy-first posture. Non-mocked tests. Absorbs #88 SHA-bound gate. Bare `Closes #88`.
- [ ] #80: `review_gate_block` persists the actual panel finding body (`governed_review.py:151` emits only a generic `panel_block` reason today) so a non-human repair sees the concrete text; persistence lands in `closeout_validators.py`. Bare `Closes #80`.
- [ ] full suite + guards + advisor-board golden green.
**Scope notes**
Decompose into 2 lanes: (a) W3 ratification_policy typed shape + gate wiring (`gate_posture.py`, `closeout_validators.py` posture, `BoardIndependence`/`lens_coverage`) + #88; (b) #80 finding-text persistence (`governed_review.py` → `closeout_validators.py`). This phase OWNS the `{governed_review.py, closeout_validators.py, gate_posture.py}` slice of the review/panel single-writer region — disjoint from SANDBOX's panel-execution slice. Parallel root; the long pole for the policy chain — start day 1.
**Non-goals**
No new hard human gate; no change to invoke_panel's byte-pinned governed path; no `panel_invoker.py`/`advisor_board/composition.py` edits (SANDBOX's slice).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py`
- `phase-loop-runtime/src/phase_loop_runtime/closeout_validators.py`
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
**Depends on**
- (none)
**Produces**
- IF-0-POLICY-1

### Phase 4 — Per-vendor review-leg sandbox (SANDBOX)
**Objective**
Make agy + grok review legs read-only by construction (REVIEWGOV D3), and restore the advisor-panel claude leg on Codex Desktop (#125) — both live in the panel-execution file cluster.
**Exit criteria**
- [ ] D3 per-vendor review-leg sandbox: agy + grok review legs run read-only by construction (staged-copy / per-vendor tool restriction), not trusting `--sandbox`; regression test that a review leg cannot write the reviewed tree.
- [ ] #125: `panel_invoker.invoke_panel()` claude leg reachable from Codex Desktop via the native adapter (not "unavailable"). Bare `Closes #125`.
- [ ] full suite + guards + advisor-board golden green.
**Scope notes**
Decompose into 2 lanes: (a) D3 per-vendor sandbox mechanism in `panel_invoker.py` + `advisor_board/composition.py`; (b) #125 codex-desktop native adapter (same `panel_invoker.py` single-writer region). This phase OWNS the `{panel_invoker.py, advisor_board/composition.py}` slice of the review/panel region — disjoint from POLICY's slice, so it runs parallel to POLICY. Parallel root; keep off `runner.py`.
**Non-goals**
No ratification-policy edits (POLICY's slice); no `governed_review.py`/`closeout_validators.py` edits.
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
**Depends on**
- (none)
**Produces**
- IF-0-SANDBOX-1

### Phase 5 — Unattended consensus + release-dispatch approval (UNATTEND)
**Objective**
Deliver W4 (consensus-substitutes-for-human for unattended runs, with a durable audit record) and the release-dispatch approval fixes (#146/#145), consuming POLICY's ratification_policy shape.
**Exit criteria**
- [ ] W4 unattended run-mode: an N-vendor consensus quorum substitutes for the EXISTING `release_guard.py:41` human merge/tag grant, writing a durable audit record; the `on_shortfall` dial (from IF-0-POLICY-1) handles 1-subscription users. Never adds a NEW human gate.
- [ ] C1 #146: a release-dispatch executor no longer mistakes its own active lock for a competitor — the caller-identity exclusion lands in `dispatch_lock.py` (the lock file already holds the PID). #145 typed operator approval propagates into release-dispatch executors. Bare `Closes #146`, `Closes #145`.
- [ ] full suite + guards + advisor-board golden green.
**Scope notes**
Single lane, serial (consumes IF-0-POLICY-1 then wires W4 + C1). Edits only `dispatch_lock.py` (caller-identity) + `release_guard.py` (the human_required grant W4 flips) — off both single-writer regions. The runner-side dispatch-identity injection at `runner.py:1374/1390` is explicitly OUT of scope here and deferred to RUNCORE2 as a noted lane.
**Non-goals**
No `runner.py` edits (the 1374/1390 dispatch call sites are RUNCORE2's); no `lease_store.py` (the concurrency is DispatchLock, not lease).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/dispatch_lock.py`
- `phase-loop-runtime/src/phase_loop_runtime/release_guard.py`
**Depends on**
- POLICY
**Produces**
- IF-0-UNATTEND-1

### Phase 6 — Governed-merge-policy consumer (GPGATE)
**Objective**
Model the agent-review-gate as governed merge policy in the governed-pipeline repo (gp#74) — the cross-repo consumer of POLICY's ratification_policy.
**Exit criteria**
- [ ] gp#74: drop a coordinating plan into governed-pipeline that models the agent-review-gate as a governed merge policy shaped by IF-0-POLICY-1, and execute it there. Cross-repo; soft-gate.
- [ ] the governed-pipeline change references the agent-harness ratification_policy contract; agent-harness phases do NOT wait on it.
**Scope notes**
Single lane, cross-repo. Consumes IF-0-POLICY-1 (models the policy POLICY freezes). Soft-gate: this phase never blocks the agent-harness phases — it coordinates execution in governed-pipeline per Cross-Cutting principle 6.
**Non-goals**
No agent-harness runtime edits; no blocking dependency onto the agent-harness merge train.
**Key files**
- governed-pipeline repo — plan drop + policy consumer (cross-repo, gp#74)
**Depends on**
- POLICY
**Produces**
- (none)

### Phase 7 — Manifest robustness (MANIFEST)
**Objective**
Make manifest-backed roadmap resolution resilient: one stale/renamed entry must not invalidate the entire manifest (#164).
**Exit criteria**
- [ ] #164: `validate_manifest` (`plan_manifest.py:137`) / manifest resolution validates PER-ENTRY — a single bad entry is skipped (orphaned), not the whole manifest silently degraded to regex at the all-or-nothing consumption in `discovery.py:1118-1122`; test proves a mixed manifest still resolves its valid entries. Bare `Closes #164`.
- [ ] full suite + guards green; the discovery ladder tests (state-precedence, completed-skip, ambiguous-blocker) still green.
**Scope notes**
Decompose into 2 lanes: (a) per-entry validation shape in `plan_manifest.py` (`validate_manifest`); (b) the resilient consumption at `discovery.py:1118-1122` + the `reconcile.py` manifest path. Touches `reconcile.py` — the FIRST link of the single-writer chain; RUNCORE2 depends on this. #165 is already closed (see Assumption #4) — not re-verified here.
**Non-goals**
No `runner.py` execution-path edits (RUNCORE2 owns those).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`
- `phase-loop-runtime/src/phase_loop_runtime/discovery.py`
- `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`
**Depends on**
- (none)
**Produces**
- IF-0-MANIFEST-1

### Phase 8 — Runner/closeout correctness batch (RUNCORE2)
**Objective**
Close the remaining runner-core correctness bugs as one single-writer serial chain, layered on top of MANIFEST's reconcile changes; also host the runner-side dispatch-identity injection deferred from UNATTEND.
**Exit criteria**
- [ ] #85: closeout/status no longer drifts when a roadmap amendment changes phase hashes (amendment-aware guard in reconcile; extends `gold_record_amendment`). Bare `Closes #85`.
- [ ] #58: closeout no longer emits an empty "active plan owned files" section / verify the :7566 fallback path; close or fix prompt population. Bare `Closes #58`.
- [ ] child-wedge family: consolidate + fix #61/#86/#90 ("quiet child, no artifacts / can't rehydrate") + #60 run-train child launch — child-liveness coverage for planner/run-train children (leg-liveness monitor is panel-only today). Bare `Closes #61, Closes #86, Closes #90, Closes #60`.
- [ ] #119: harness-agnostic compact operator stop summaries in closeout. Bare `Closes #119`.
- [ ] runner-side dispatch-identity injection: pass caller identity into the `dispatch_lock.py` exclusion at the `runner.py:1374/1390` call sites (the piece UNATTEND left as a non-goal); if UNATTEND ran the same pass, sequence this lane after it.
- [ ] full suite + guards green; RUNCORE (0.7.0) regression tests unchanged.
**Scope notes**
Decompose into 5 lanes, STRICTLY SERIAL (single-writer `runner.py` + `reconcile.py`): (a) #85 amendment guard; (b) #58 closeout owned-files; (c) child-wedge #61/#86/#90/#60 (`runner.py` + `train_runner.py`); (d) #119 operator summaries; (e) runner-side dispatch-identity injection (consumes UNATTEND's `dispatch_lock.py` contract). Re-resolve all line anchors against post-MANIFEST head.
**Non-goals**
No manifest-validation edits (MANIFEST owns them).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/handoff.py`
**Depends on**
- MANIFEST
**Produces**
- (none)

## Phase Dependency DAG
```
SKILLREF   ── parallel root (owns all execute-phase SKILL edits, incl. draft-PR protocol)
PUSHFLOW   ── parallel root (cli-arg default + doctor; NO skill edits, NO runner.py)
POLICY   ──┬─► UNATTEND   (W4 + C1 consume IF-0-POLICY-1)
           └─► GPGATE     (gp#74 cross-repo, soft-gate)
SANDBOX    ── parallel root (panel-execution slice; parallel to POLICY)
MANIFEST ──► RUNCORE2     (single-writer reconcile→runner chain; hosts UNATTEND's runner-side C1 injection)
```
Critical path: max(POLICY→UNATTEND, MANIFEST→RUNCORE2). Five phases start on day 1 (SKILLREF, PUSHFLOW, POLICY, SANDBOX, MANIFEST); UNATTEND + GPGATE wait on POLICY; RUNCORE2 waits on MANIFEST. GPGATE is a soft-gate and never blocks the merge train.

## Execution Notes
- Run `/claude-plan-phase <ALIAS>` then `/claude-execute-phase <alias>` per phase. SKILLREF, PUSHFLOW, POLICY, SANDBOX, MANIFEST can be planned + executed concurrently; UNATTEND + GPGATE after POLICY merges; RUNCORE2 after MANIFEST merges (and after UNATTEND if the runner-side C1 lane runs the same pass).
- Distribute executor harnesses to spread token use: SKILLREF (docs/light) can run via codex/gemini executors; POLICY/SANDBOX/UNATTEND/MANIFEST/RUNCORE2 are claude-grade. GPGATE is a cross-repo coordination phase (plan drop + governed-pipeline execution).
- Review/panel region: POLICY and SANDBOX write disjoint file slices of the same cluster — safe to run in parallel because no file is touched by both. Do not let any other phase enter either single-writer region.
- CR contention: up to 5 lanes CR concurrently on the shared codex/grok/agy subscriptions — stagger 5–10s, retry, empty leg = contention not verdict, kill by PID only, inline-diff fallback when a CLI can't read files.
- No RELEASE phase here — a separate release (chunk-assembly → stage bump → release-readiness panel → tag) ships these once merged.

## Verification
- `phase-loop validate-roadmap specs/phase-plans-v10.md` → OK (8 phases).
- Post-merge: `git -C <repo> rev-list --count origin/main..HEAD` on a worktree after a closeout → 0 unpushed (PUSHFLOW); `phase-loop advisor-board <artifact>` under an unattended policy cuts a decision on consensus (UNATTEND, per IF-0-POLICY-1); a review leg cannot write the reviewed tree (SANDBOX); a mixed manifest with one bad entry still resolves valid entries (MANIFEST); the reflection cache is empty (SKILLREF); issues #80/#85/#58/#61/#86/#90/#60/#119/#125/#146/#145/#88/#164 CLOSED. (#165 already closed by #167; gp#74 tracked cross-repo as a soft-gate.)
