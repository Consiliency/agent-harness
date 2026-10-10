---
name: skill-improvement-planner
description: "OpenCode skill feedback aggregator. Use when the user wants to review OpenCode skill reflections, aggregate recurring feedback, or plan improvements to `<harness>-*` skills. Produces an improvement plan for <harness>-skill-editor and does not edit skills itself."
---

# OpenCode Skill Improvement Planner

Aggregates reflection files for OpenCode skills and produces a structured improvement plan. It does not edit skills; `<harness>-skill-editor` applies the plan.

## Core Rules

Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.

- Canonical source for every `<harness>-*` workflow skill is `skills-src/opencode/<harness>-<skill>/SKILL.md` in the agent-harness checkout (IF-0-CANON-1, `docs/phase-loop/skills-canonical-source.md`). `phase-loop-skills/` and `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/` are generated from it; installed runtime roots are installed from those. Plan edits against `skills-src/` only.
- Planning only. Do not modify `SKILL.md` files.
- Build the input with `python3 -m phase_loop_runtime.reflection_corpus collect --out-dir <dir> --min-reflections <N>`, or read the `--corpus <dir>` that `maintain-skills` already prepared. The collector scans every harness skill root, excludes `archive/`, and applies the capture quality filter. Do not hand-glob reflections.
- Act only on recurring evidence unless the user explicitly asks to apply one-off feedback.
- Do not spawn subagents unless the user explicitly asks for delegated analysis.

## Pipeline

`skills-src/opencode/<harness>-<skill>/` → `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py` (→ `phase-loop-skills/`) → `python3 phase-loop-runtime/scripts/sync_skills_bundle.py` (→ packaged `skills_bundle/`) → installed runtime roots. Name target files under `skills-src/`; never treat bundle or installed copies as source of truth.

## Inputs

- `--target <skill-name>`: plan for one skill.
- `--min-reflections <N>`: default `2`.
- `--corpus <dir>`: a collector output directory (`bundle.md` + `manifest.json`); default is to run the collector.
- `--output <path>`: default `resolve_skill_bundle_root("opencode")/<harness>-skill-improvement-planner/plans/plan-v<N>-<ISO>.md`.

## Workflow

1. Collect the corpus (Core Rules) and read `<dir>/bundle.md` and `<dir>/manifest.json`. In scope, across every harness prefix:
   - `<harness>-phase-roadmap-builder`
   - `<harness>-plan-phase`
   - `<harness>-execute-phase`
   - `<harness>-plan-detailed`
   - `<harness>-execute-detailed`
   - `<harness>-task-contextualizer`
   - `<harness>-skill-improvement-planner`
   - `<harness>-skill-editor`
   - `<harness>-advisor-board`
   - `<harness>-phase-loop`
   - `<harness>-run-train`
   - `advisor-panel` reflections count as `advisor-board`.
2. Use the collector's parse; each reflection carries its manifest id (`R0001`):
   - `What worked`;
   - `What didn't` (also headed `What did not`) — the primary friction evidence; a recommendation may rest on it alone;
   - `Improvements to SKILL.md`;
   - raw body, tagged `unstructured`, when headings are missing.
3. Gate on minimum evidence:
   - zero admitted reflections: report that there is nothing to aggregate;
   - skills absent from manifest `ready_skills`: record as skipped.
4. Aggregate recommendations:
   - when the bundle exceeds one context, aggregate one skill section at a time, then run one cross-cutting pass over the per-skill results;
   - group recurring themes by skill;
   - separate actionable changes from speculative notes;
   - flag contradictions instead of resolving them silently;
   - reject repo-specific recommendations unless the target skill is intentionally repo-specific;
   - already-covered: read the target `skills-src/` `SKILL.md` first; when the guidance exists but is buried or weak, propose a wording or placement change, not a duplicate addition;
   - decision-changing: keep only edits that change what a future agent does, not edits that only add text;
   - structural-mechanism: when a lint, script, metadata flag or runtime check could enforce the rule cheaply, route it to a filed `agent-harness#N` issue (`docs/registers/deferred-findings.md`) instead of skill prose.
5. Produce a plan with:
   - frontmatter listing `corpus_manifest` and the manifest's `reflections_consumed` paths;
   - recommendations by skill;
   - cross-cutting recommendations;
   - mechanism candidates (route to a filed issue, not a skill edit);
   - speculative notes;
   - contradictions;
   - archival directive for `<harness>-skill-editor`.

## Plan Format

```markdown
---
from: <harness>-skill-improvement-planner
timestamp: <ISO>
min_reflections: <N>
corpus_manifest: <absolute path to manifest.json>
reflections_consumed:
  - <absolute path>
---

# OpenCode skill improvement plan — <ISO>

## Summary

## Recommendations by skill

### <skill-name>
- **Change**: <directive>
  - **Rationale**: <evidence>
  - **Target**: `skills-src/opencode/<harness>-<skill>/SKILL.md`
  - **Supporting reflections**: <manifest ids, e.g. R0012, R0040>

## Cross-cutting recommendations

## Mechanism candidates

## Speculative / low-confidence notes

## Contradictions surfaced

## Archival directive for <harness>-skill-editor

After the recommendations apply, run `python3 -m phase_loop_runtime.reflection_corpus archive --manifest <corpus_manifest>`, adding `--exclude <path>` for each reflection that supports a failed recommendation.
```

## Closeout

Closeout payload shape is defined by `EmitPhaseCloseout` in `phase_loop_runtime/baml_src/emit_phase_closeout.baml` (if that path is absent in the checkout, use the operator/prompt-supplied field contract or the installed `phase_loop_runtime` package — the missing vendored BAML source is not a blocker); keep skill text focused on value selection and handoff routing, not duplicated field ceremony.

In Default mode, write the plan only if the user asked for an artifact. Otherwise summarize the recommendations. Do not archive reflections; that is the editor's job.

If writing self-improvement state, resolve handoff writes through `shared/phase-loop/handoff_path.py` and the repo-local handoff resolver; legacy harness handoff roots are read only for migration. Follow the repo/branch/run-isolated layout from `phase_loop_runtime.skill_paths` and use OpenCode paths only:

- Reflection: `resolve_skill_bundle_root("opencode")/<harness>-skill-improvement-planner/reflections/<repo_hash>/<branch_slug>/<run_id>.md`
- Handoff: `<repo>/.dev-skills/handoffs/<harness>-skill-improvement-planner/<run_id>.md`
- Latest handoff pointer: `<repo>/.dev-skills/handoffs/<harness>-skill-improvement-planner/latest.md`

Handoff frontmatter must include `from: <harness>-skill-improvement-planner`, `timestamp:`, `repo:`, `repo_root:`, `branch:`, `branch_slug:`, `commit:`, `run_id:`, and `artifact:`. Update `latest.md` with the same handoff content.
