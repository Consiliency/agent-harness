# Big-picture fix plan — post-0.7.0 (gaps · refinements · bugs)
Date: 2026-07-11 · Baseline: agent-harness 0.7.0 (CLEANSHIP shipped) · Source: SKILLREFLECT digest (30 reflections, code-verified) + open-issue backlog + deferred architecture.

## How this was built
Reflections digested → each theme VERIFIED against origin/main skill sources (still-live vs already-fixed) → merged with the open-issue backlog + the deferred REVIEWGOV design → grouped into workstreams with severity/effort/deps.

---

## Workstream A — SKILL-INSTRUCTION refinements (SKILLREFLECT)
Skills ship from agent-harness `skills-src/<harness>/<skill>/SKILL.md` (neutral base = codex; each harness authored independently → regen → sync → parity-gated). "All 4" = claude/codex/gemini/opencode sources edited together.

| ID | Fix | Verified state | Effort | Sources |
|----|-----|----------------|--------|---------|
| **A1** | **roadmap-builder: add a tight "Validator Format Contract" block up front** — alias `[A-Za-z0-9]+` (hyphenated gate `XG-0`→alias `XG0`, hyphen name in prose); nothing after `(ALIAS)` on a heading; each `**Field**` on its own line; `Key files`/`Produces`/`Depends on` bulleted; lane hint MUST contain literal "decompose into N lanes"/"Single lane"/"preamble"; a malformed heading de-registers the phase → CASCADES → fix heading/alias errors FIRST | STILL-LIVE (only a 1-line template ref at :282). **Bit us 3× this session** (cleanship round-trips: PORTAL parenthetical, alias hyphens) | **S** | all 4 |
| **A2** | **Lead with `phase_loop_runtime.skill_paths` resolver** (`resolve_handoff_root`/`resolve_reflection_root`), demote `shared/phase-loop/handoff_path.py` to fallback | STILL-LIVE (skills lead with handoff_path.py at :89/:312 — "frequently absent" per ×5 reflections) | S | all 4 (roadmap-builder, plan-phase, plan-detailed, execute-phase) |
| **A3** | **skip-Explore-when-context-in-session + proportionality gate** — if the main thread already holds the file:line facts (authored earlier this session), summarize into `## Context` and skip the Explore fan-out; small owned-surface + barely-parallel → recommend plan-detailed | Recurring ×4; verify current wording | S/M | plan-phase, plan-detailed |
| **A4** | **multi-roadmap-repo note** — disjoint alias prefix when other roadmaps exist; prefer create-mode over silent append across initiatives (ties to the discovery completed-skip we shipped) | Recurring ×3; partially covered runtime-side | S | roadmap-builder |
| **A5** | ExitPlanMode polish for roadmap-builder/plan-phase to match plan-detailed's clean Step-6 two-path shape | LARGELY DONE (#87 + conditional handling exists) | S | roadmap-builder, plan-phase |
| **A6** | After A1–A5: regen bundle (parity-gated) + **clear the digested reflection cache** (`~/.codex/skills/*/reflections/`) for a fresh 0.7.0 start | — | S | — |

Clear-cache verdict: **safe AFTER A1–A5 land** — the recurring signal is captured; the residual reflections are run-specific.

---

## Workstream B — phase-loop RUNTIME bugs (open issues)
| ID | Issue | Scope | Sev | Effort |
|----|-------|-------|-----|--------|
| **B1** | **#164** manifest fragility: ONE stale/renamed entry invalidates the ENTIRE manifest (validate_manifest all-or-nothing) → silent degrade to regex discovery | per-entry validation instead of all-or-nothing; found this session | **HIGH** | M |
| **B2** | **#165** task-message resolver assumes a Codex app-server 0.144.1 persistence shape it doesn't preserve (clientUserMessageId as stored id; 2 adjacent text inputs) — live-disproven | re-derive the resolver against the real 0.144.1 shape | HIGH | M |
| **B3** | **#85** closeout/status drift when roadmap amendment changes phase hashes | amendment-aware guard in reconcile; structural, still-present | MED | M |
| **B4** | **#58** closeout empty "active plan owned files" (refusal substantially fixed by :7566 fallback; prompt-fill in BAML unverified) | verify/close or fix prompt population | LOW | S |
| **B5** | **child-wedge family: consolidate #61 + #86 + #90** ("quiet child, no artifacts / can't rehydrate") + **#60** run-train | one consolidated diagnosis; child-liveness for planner/run-train children (leg-liveness monitor is panel-only today) | MED | M/L |
| **B6** | **#80** persist actionable panel finding text on review_gate_block; **#119** operator stop summaries; **#125** codex-desktop claude leg native adapter | operator-UX / debuggability | LOW | S each |

---

## Workstream C — executor-governance / release-dispatch
| ID | Issue | Sev | Effort |
|----|-------|-----|--------|
| **C1** | **#146** release-dispatch concurrency guard mistakes current executor for competitor (blocks its own release phase) + **#145** propagate typed operator approval into release-dispatch executors | MED | M |
| **C2** | **#84** (--phase repairs blocked SEAL instead of dispatching): KEEP OPEN — no repro on 0.7.0; concurrent-path variant already hardened. Close if it never reproduces. | LOW | — |

---

## Workstream D — REVIEW / RATIFICATION (REVIEWGOV W3/W4 — the deferred architecture)
This is the biggest design piece — the review-panel concern from `plans/bigpicture-review-ratification-and-backlog-20260711.md`. W1 (auth-aware boards) + W2 + the runnable board + streaming verdicts SHIPPED in 0.7.0. Remaining:
- **D1 — W3 parameterized ratification policy**: per-gate required strength (min vendors / lens_coverage / consensus); achievable-vs-required → escalate-human OR proceed-degraded; human-required OPT-IN. Absorbs **#88** (SHA-bound agent-review-gate) + **gp#74** (model agent-review-gate as governed merge policy). Effort L.
- **D2 — W4 consensus-substitutes-for-human** (unattended run-mode): N-vendor consensus quorum stands in for the human merge/tag grant with a durable audit record; the achievable<required dial handles 1-subscription users. Absorbs **#145/#146** (release-dispatch approval). This is exactly the pattern we EXERCISED this session (release-readiness panel cut the tag) — D2 makes it first-class in the runtime. Effort L.
- **D3 — per-vendor review-leg sandboxing**: agy + grok CLIs both run write-capable review legs (proven this session — agy mutated a worktree twice; grok auto-approves writes). The board/CR path must sandbox review legs per-vendor (staged-copy or a `--tools`/deny-list equivalent per vendor), not trust `--sandbox`. Effort M.

---

## Workstream E — grok / security hardening
- **E1 — #154** grok `spawn_subagent` un-disableable via CLI in 0.2.93 (both `--disallowed-tools` and `--no-subagents` behaviorally refuted). The named tripwire test flags when a future grok honors it. ACTION: revisit on grok CLI upgrade, or find a config/profile-level lever. Keep open; low urgency (execute leg is proof-gated). Effort S-on-upgrade.

## Workstream F — cross-repo / fleet
- **F1 — portal#208** prod Supabase migration-history drift (6 agent-board migrations applied from unmerged branches → main deploys red). Owner: agent-board/fleet-gateway lane. NOT ours; tracked.

---

## Suggested sequencing (a future roadmap)
```
A (SKILLREFLECT: A1→A6) ── parallel root, self-contained skills-src → clears the cache
B1 (#164 manifest) ─┐
B2 (#165 resolver) ─┼─ RUNTIME bug batch (single-writer discipline on runner/discovery/reconcile as before)
B3 (#85) ···········┘
D1 (W3) → D2 (W4)  ── the ratification-policy arc (largest; D2 makes tonight's release-panel pattern native); D3 sandboxing feeds it
C1 (#146/#145) ──── folds into D2 (release-dispatch approval == consensus-substitution)
B5/B6/B4 ────────── lighter runtime/UX batch, parallel
E1 ─── deferred (grok upgrade) ; F1 ─── portal owners
```
Critical insight: **C1 + D2 are the same problem** (who/what approves a governed release), and D2 is the natural home for the release-dispatch fixes. A1 is the cheapest highest-ROI item (recurring + self-evident). B1/B2 are the two real HIGH-severity runtime bugs.

## Recommended first cut (if scoping a next roadmap now)
1. **A1–A6 (SKILLREFLECT)** — S, high-ROI, unblocks a clean reflection reset.
2. **B1 (#164) + B2 (#165)** — the two HIGH runtime bugs.
3. **D1→D2 + D3 + C1** — the ratification-policy arc (the review-panel concern), consuming #88/#145/#146/gp#74.
Everything else (B3-B6, E1, F1) is a lighter follow-on batch.
