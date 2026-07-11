# Phase roadmap v10 — POST070FIX (post-0.7.0 gaps, refinements, bugs)

## Context
0.7.0 (CLEANSHIP) shipped. This roadmap closes the remaining backlog synthesized from three sources: the SKILLREFLECT digest of 30 code-verified skill reflections, the open agent-harness issue backlog, and the deferred REVIEWGOV review-ratification architecture — plus a newly-surfaced local/origin divergence gap (PUSHFLOW). Built for maximum parallelism: 4 disjoint parallel-root phases + one single-writer reconcile→runner chain. Full findings in `plans/bigpicture-fix-plan-post-0.7.0-20260711.md`. Baseline: origin/main @ 6cdbbd3 (includes #167, which addresses #165).

## Architecture North Star
```
 parallel roots (disjoint file sets)          single-writer chain
 ┌───────────┐ ┌──────────┐ ┌────────┐ ┌──────┐   ┌──────────┐   ┌──────────┐
 │ SKILLREF  │ │ PUSHFLOW │ │ REVGOV2│ │ OPUX │   │ MANIFEST │ → │ RUNCORE2 │
 │ skills-src│ │ git/plumb│ │ board/ │ │ ui   │   │ discovery│   │ runner.py│
 │  + regen  │ │ worktree │ │ gate/  │ │      │   │ reconcile│   │ reconcile│
 │  + clear  │ │ publish  │ │ lease  │ │      │   │ (manifest│   │ train    │
 └───────────┘ └──────────┘ └────────┘ └──────┘   └──────────┘   └──────────┘
 SKILL gaps    local≠origin  ratify-   operator   #164 manifest   #85/#58/
 (validator    visibility    policy    UX debt    all-or-nothing  child-wedge
  format,      (push-on-     (W3/W4)                                +#119
  skill-paths) closeout,     +#146/45
               ahead-alarm)  +D3 sandbox
```

## Assumptions (fail-loud if wrong)
1. origin/main @ 6cdbbd3 or later; skills ship from agent-harness `skills-src/<harness>/<skill>/` (neutral base = codex; regen → sync → parity-gated); editing shared prose means all 4 harness sources.
2. `resolve_closeout_push_target` (git_topology.py:72) is consumed by publishing.py but push is NOT default in every closeout mode — PUSHFLOW makes it default. If push is already universal, PUSHFLOW #1 narrows to config-audit + the ahead-alarm.
3. Release-dispatch concurrency (#146) is enforced via `lease_store.py` (self-lease seen as competing) — disjoint from runner.py. If it lives in runner, C1 moves into RUNCORE2's chain (fail-loud: re-DAG).
4. #167 addresses #165 (task-message persistence) — MANIFEST verifies and closes #165, or reopens the residual as fail-loud.
5. The autonomy-first gate posture exists (validators never set human_required; review_gate_block/warn) — W3 EXTENDS it, does not replace it.

## Non-Goals
- No new hard human_required gates (autonomy-first: warn default, block opt-in) — including W3/W4.
- No grok spawn_subagent fix (#154) — undeliverable via CLI 0.2.93; the tripwire watches; revisit on grok upgrade.
- No portal#208 reconciliation (portal/fleet-gateway owners) — tracked, out of scope.
- No version bump inside fix phases — a follow-on RELEASE (not in this roadmap) stages the next tag.
- #84 stays open (no repro) unless RUNCORE2 reproduces it.

## Cross-Cutting Principles
1. runner.py + reconcile.py are SINGLE-WRITER: only the MANIFEST→RUNCORE2 chain edits them; every other phase must keep off those files (region-audit before editing).
2. Verify against a freshly-fetched origin/main, never a possibly-stale working tree.
3. Fold in any new bug noticed mid-execution as a fix (standing rule).
4. Each phase emits a `.consiliency/changelog.d/CHANGELOG-<alias>.md` chunk (basename starts with CHANGELOG — docs-audit `**/CHANGELOG*` glob); a follow-on RELEASE assembles them.
5. CR = 4-vendor (grok-4.5 / gpt-5.6-sol / Gemini-3.1-pro / claude-**fable** — Fable seat is explicit `model: fable`, never inherited Opus); agy + grok review legs run READ-ONLY (grok `--tools read_file,grep,list_dir,search_tool`; agy on a staged copy — both are write-capable). Bare `Closes #N` for auto-close (qualified fleet form does NOT auto-close). Split-verdict: concrete-defects-fixed + peer-confirm = convergent; adjudicate out-of-scope findings.
6. Cross-repo work (gp#74) drops a plan into the target repo and coordinates its execution there.

## Top Interface-Freeze Gates
1. IF-0-PUSHFLOW-1 — the closeout-push contract (`push_on_closeout` default + `--no-push`/no-remote fallback) + `commits_ahead_of_origin` field on the worktree/closeout status.
2. IF-0-REVGOV2-1 — the `ratification_policy` shape (per-gate required strength: min vendors / lens_coverage / consensus; achievable-vs-required → escalate|proceed-degraded) that W4 + C1 consume.
3. IF-0-REVGOV2-2 — the per-vendor review-leg sandbox contract (D3).
4. IF-0-MANIFEST-1 — per-entry manifest validation result shape (one bad entry no longer invalidates the whole manifest).

## Phases

### Phase 1 — Skill-reflection refinements (SKILLREF)
**Objective**
Fold the recurring, code-verified skill-reflection learnings into the phase-loop authoring skills, then clear the digested reflection cache for a fresh 0.7.0 start.
**Exit criteria**
- [ ] roadmap-builder SKILL.md carries a "Validator Format Contract" block (alias `[A-Za-z0-9]+`; no decoration after `(ALIAS)`; each `**Field**` on its own line; lists bulleted; lane hint contains literal "decompose into N lanes"/"Single lane"; malformed heading cascades → fix heading first).
- [ ] roadmap-builder + plan-phase + plan-detailed + execute-phase lead with the `phase_loop_runtime.skill_paths` resolver; `handoff_path.py` demoted to fallback.
- [ ] skip-Explore-when-context-in-session + proportionality carve-out present in plan-phase + plan-detailed; multi-roadmap alias/create-mode note in roadmap-builder.
- [ ] all 4 harness sources edited, `regenerate_skills_bundle.py` + `sync_skills_bundle.py` run, `test_skills_canon_parity.py` green.
- [ ] `~/.codex/skills/*/reflections/` cleared (after the above lands) with a one-line note; full suite + guards green.
**Scope notes**
Decompose into 3 lanes: (a) roadmap-builder format-contract + multi-roadmap note; (b) skill-paths resolver across all 4 skills; (c) skip-Explore/proportionality + regen + cache-clear. Fully disjoint from runtime code — a parallel root.
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
Stop local branches diverging 70–100 commits ahead of origin: push on closeout by default, surface an ahead-of-origin signal, and open draft PRs early so in-flight work is visible to other developers.
**Exit criteria**
- [ ] closeout pushes the branch to `resolve_closeout_push_target()` by default after a successful closeout commit; `--no-push` flag + graceful no-remote fallback; test proves push fires and the flag suppresses it.
- [ ] `commits_ahead_of_origin: N` mirrors `main_behind` in worktree/closeout status + `phase-loop doctor`; WARN default, soft-block above a threshold (opt-in, never human_required).
- [ ] executor/skill protocol: push branch + open a DRAFT PR on the first commit of a phase (documented in the execute-phase skill).
- [ ] full suite + guards green.
**Scope notes**
Decompose into 2 lanes: (a) closeout-push-default + no-push flag (git_topology/publishing) + ahead-of-origin signal (worktree_index/doctor); (b) draft-PR-early skill-protocol wording (execute-phase skill, all 4 harnesses) + the doctor/status surfacing. Git-plumbing files, disjoint from runner.py — a parallel root. Single-writer caution: do NOT touch runner.py's closeout call path if it exists; push lives in publishing.py.
**Non-goals**
No change to `--closeout-mode` semantics; no auto-merge.
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/{git_topology.py,publishing.py,worktree_index.py,doctor*.py}`
- execute-phase SKILL sources
**Depends on**
- (none)
**Produces**
- IF-0-PUSHFLOW-1

### Phase 3 — Review-ratification policy (REVGOV2)
**Objective**
Deliver the deferred REVIEWGOV W3/W4 architecture — parameterized ratification policy + consensus-substitutes-for-human for unattended runs + per-vendor review-leg sandboxing — and fold in the release-dispatch approval fixes, making the release-readiness-panel pattern we used to ship 0.7.0 native in the runtime.
**Exit criteria**
- [ ] `ratification_policy` per gate (plan-ratify/design-ratify/pre-merge-CR/release-dispatch): required min-vendors / lens_coverage / consensus; achievable<required → escalate-human OR proceed-degraded-with-audit; extends (not replaces) the autonomy-first posture. Non-mocked tests. (absorbs #88 SHA-bound gate)
- [ ] W4 unattended run-mode: N-vendor consensus quorum substitutes for the human merge/tag grant with a durable audit record; the achievable<required dial handles 1-subscription users.
- [ ] D3 per-vendor review-leg sandbox: agy + grok review legs run read-only by construction (staged-copy / per-vendor tool restriction), not trusting `--sandbox`; regression test that a review leg cannot write the reviewed tree.
- [ ] C1 #146: a release-dispatch executor no longer mistakes its own active lease for a competitor (`lease_store`); #145 typed operator approval propagates into release-dispatch executors. Bare `Closes #146`, `Closes #145`, `Closes #88`.
- [ ] gp#74 (model agent-review-gate as governed merge policy): drop a coordinating plan into governed-pipeline and execute it there (the gp consumer of this policy). Cross-repo.
- [ ] full suite + guards + advisor-board golden green.
**Scope notes**
Decompose into 4 lanes: (a) W3 ratification_policy shape + gate wiring (gate_posture/closeout_validators posture, BoardIndependence/lens_coverage); (b) W4 consensus-for-human + unattended run-mode + audit; (c) D3 per-vendor review-leg sandbox (advisor_board/panel_invoker/composition); (d) C1 release-dispatch lease fix (#146/#145) + the gp#74 cross-repo plan. Serial dependency a→b→C1 (b + C1 consume the policy shape); D3 parallel. Disjoint from runner.py/reconcile.py. The long pole — start day 1.
**Non-goals**
No new hard human gate; no change to invoke_panel's byte-pinned governed path.
**Key files**
- `advisor_board/*`
- `gate_posture.py`
- `closeout_validators.py`
- `lease_store.py`
- `panel_invoker.py`
- `composition.py`
- governed-pipeline (cross-repo
- gp#74)
**Depends on**
- (none)
**Produces**
- IF-0-REVGOV2-1
- IF-0-REVGOV2-2

### Phase 4 — Operator-UX debt (OPUX)
**Objective**
Clear the low-severity operator-visibility issues that are disjoint from the runtime hot paths.
**Exit criteria**
- [ ] #80: `review_gate_block` persists the actual panel finding body (not a generic summary) for non-human repair. Bare `Closes #80`.
- [ ] #125: advisor-panel claude leg reachable from Codex Desktop via the native adapter (not "unavailable"). Bare `Closes #125`.
- [ ] full suite + guards green.
**Scope notes**
Decompose into 2 lanes: (a) #80 finding-text persistence (doc_delta_validator/closeout persistence — audit it is NOT in the runner single-writer region; if it is, move to RUNCORE2); (b) #125 codex-desktop adapter (panel adapter — coordinate with REVGOV2 if it touches panel_invoker). Parallel root; keep off runner.py.
**Non-goals**
#119 operator stop summaries → handled in RUNCORE2 (touches closeout).
**Key files**
- `doc_delta_validator.py`
- panel/codex-desktop adapter modules
**Depends on**
- (none)
**Produces**
- (none)

### Phase 5 — Manifest robustness (MANIFEST)
**Objective**
Make manifest-backed roadmap resolution resilient: one stale/renamed entry must not invalidate the entire manifest; verify and close the #167-addressed #165.
**Exit criteria**
- [ ] #164: `validate_manifest` / manifest resolution validates PER-ENTRY — a single bad entry is skipped (orphaned), not the whole manifest silently degraded to regex; test proves a mixed manifest still resolves its valid entries. Bare `Closes #164`.
- [ ] #165 verified fixed by #167 → closed (or the residual reopened fail-loud with evidence).
- [ ] full suite + guards green; the discovery ladder tests (state-precedence, completed-skip, ambiguous-blocker) still green.
**Scope notes**
Decompose into 2 lanes: (a) per-entry manifest validation (discovery.py + reconcile.py manifest path); (b) #165/#167 verification + issue-op. Touches reconcile.py/discovery — the FIRST link of the single-writer chain; RUNCORE2 depends on this.
**Non-goals**
No runner.py execution-path edits (RUNCORE2 owns those).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/{discovery.py,reconcile.py}`
**Depends on**
- (none)
**Produces**
- IF-0-MANIFEST-1

### Phase 6 — Runner/closeout correctness batch (RUNCORE2)
**Objective**
Close the remaining runner-core correctness bugs as one single-writer serial chain, layered on top of MANIFEST's reconcile changes.
**Exit criteria**
- [ ] #85: closeout/status no longer drifts when a roadmap amendment changes phase hashes (amendment-aware guard in reconcile; extends `gold_record_amendment`). Bare `Closes #85`.
- [ ] #58: closeout no longer emits an empty "active plan owned files" section / verify the :7566 fallback path; close or fix prompt population. Bare `Closes #58`.
- [ ] child-wedge family: consolidate + fix #61/#86/#90 ("quiet child, no artifacts / can't rehydrate") + #60 run-train child launch — child-liveness coverage for planner/run-train children (leg-liveness monitor is panel-only today). Bare `Closes #61, Closes #86, Closes #90, Closes #60`.
- [ ] #119: harness-agnostic compact operator stop summaries in closeout. Bare `Closes #119`.
- [ ] full suite + guards green; RUNCORE (0.7.0) regression tests unchanged.
**Scope notes**
Decompose into 4 lanes, STRICTLY SERIAL (single-writer runner.py + reconcile.py): (a) #85 amendment guard; (b) #58 closeout owned-files; (c) child-wedge #61/#86/#90/#60 (runner + train_runner); (d) #119 operator summaries. Re-resolve all line anchors against post-MANIFEST head.
**Non-goals**
No manifest-validation edits (MANIFEST owns them).
**Key files**
- `phase-loop-runtime/src/phase_loop_runtime/{runner.py,reconcile.py,train_runner.py,handoff.py}`
**Depends on**
- MANIFEST
**Produces**
- (none)

## Phase Dependency DAG
```
SKILLREF   ── parallel root
PUSHFLOW   ── parallel root
REVGOV2    ── parallel root (long pole; internal a→b→C1, D3 parallel)
OPUX       ── parallel root
MANIFEST ──► RUNCORE2   (single-writer reconcile→runner chain)
```
Critical path: max(REVGOV2, MANIFEST→RUNCORE2). Five phases start on day 1; only RUNCORE2 waits (on MANIFEST).

## Execution Notes
- Run `/claude-plan-phase <ALIAS>` then `/claude-execute-phase <alias>` per phase. SKILLREF, PUSHFLOW, REVGOV2, OPUX, MANIFEST can be planned + executed concurrently; RUNCORE2 after MANIFEST merges.
- Distribute executor harnesses to spread token use: SKILLREF/OPUX (docs/light) can run via codex/gemini executors; REVGOV2/RUNCORE2/MANIFEST are claude-grade.
- CR contention: up to 5 lanes CR concurrently on the shared codex/grok/agy subscriptions — stagger 5–10s, retry, empty leg = contention not verdict, kill by PID only, inline-diff fallback when a CLI can't read files.
- No RELEASE phase here — a separate release (chunk-assembly → stage bump → release-readiness panel → tag) ships these once merged.

## Verification
- `phase-loop validate-roadmap specs/phase-plans-v10.md` → OK.
- Post-merge: `git -C <repo> rev-list --count origin/main..HEAD` on a worktree after a closeout → 0 unpushed (PUSHFLOW); `phase-loop advisor-board <artifact>` under an unattended policy cuts a decision on consensus (REVGOV2); a mixed manifest with one bad entry still resolves valid entries (MANIFEST); the reflection cache is empty (SKILLREF); issues #80/#85/#58/#61/#86/#90/#60/#119/#125/#146/#145/#88/#164 CLOSED.
