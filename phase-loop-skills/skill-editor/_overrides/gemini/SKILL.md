---
name: skill-editor
description: "Harness skill editor. Use when the user wants to apply an improvement plan produced by <harness>-skill-improvement-planner to Harness skill files. Edits only targeted `<harness>-*` skills by default, archives consumed reflections after successful edits, and uses structured file-editing tools for manual changes."
---

# Harness Skill Editor

Applies a structured improvement plan to Harness skill files. It is deliberately narrower than arbitrary skill editing: it consumes plans from `<harness>-skill-improvement-planner` and updates the named target skills.

## Core Rules

Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.

- Canonical source for every `<harness>-*` workflow skill is `skills-src/gemini/<harness>-<skill>/SKILL.md` in the agent-harness checkout (IF-0-CANON-1, `docs/phase-loop/skills-canonical-source.md`). Edit only there; `phase-loop-skills/` and the packaged `skills_bundle/` are generated, and a hand edit to them fails the parity gate.
- After edits, run `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py` then `python3 phase-loop-runtime/scripts/sync_skills_bundle.py`; one source edit fans out to every generated copy.
- Read the improvement plan and target `SKILL.md` before editing.
- Use the active session's file-editing tool for manual edits.
- Edit only skills named by the plan.
- Default target set is `<harness>-*` skills. Do not edit the original Claude-oriented skills unless the plan explicitly names them and the user confirms that scope.
- Preserve skill frontmatter validity.
- Do not push or commit unless the user explicitly requests it.
- Archive consumed reflections only after all recommendations citing them succeeded.

## Pipeline

`skills-src/gemini/<harness>-<skill>/` → `regenerate_skills_bundle.py` (→ `phase-loop-skills/`) → `sync_skills_bundle.py` (→ packaged `skills_bundle/`) → installed runtime roots. Edit only the first tier during this skill-editor workflow.

## Inputs

- Plan path: explicit path, or latest `resolve_skill_bundle_root("gemini")/<harness>-skill-improvement-planner/plans/plan-v*.md`.
- `--dry-run`: parse and report intended edits without changing files.

If no plan path is explicit, first check the current repo and branch handoff from `<harness>-skill-improvement-planner` using the repo/branch/run-isolated layout from `phase_loop_runtime.skill_paths`: read the repo-local handoff resolver target `.dev-skills/handoffs/<harness>-skill-improvement-planner/latest.md`, validate `from`, `repo`, `repo_root`, `branch`, `branch_slug`, `commit`, and `artifact`, then use the artifact only if it exists under the current repo root. Ignore missing or mismatched handoffs unless the user explicitly asks to reuse cross-branch state.

## Workflow

1. Resolve and read the plan.
2. Parse:
   - `corpus_manifest` and `reflections_consumed`;
   - recommendations by skill;
   - cross-cutting recommendations;
   - contradictions.
3. If contradictions exist, stop and ask the user how to resolve them unless the plan already contains a resolution.
4. Validate target skills:
   - source path `skills-src/gemini/<harness>-<skill>/SKILL.md` under the agent-harness checkout must exist; when it does not, mark the recommendation failed (never edit an installed or generated copy instead);
5. For `--dry-run`, report the target files and recommendation summaries, then stop.
6. Apply recommendations:
   - group changes per target skill to avoid conflicting edits;
   - keep `SKILL.md` concise;
   - move lengthy examples into `references/`;
   - update `agents/openai.yaml` when display metadata becomes stale.
7. Validate:
   - YAML frontmatter parses;
   - `name` matches the skill directory intent;
   - `description` clearly states trigger scope and non-scope;
   - referenced files exist;
   - `phase-loop-runtime/tests/test_skills_canon_parity.py` and `test_skills_bundle_drift.py` pass after regeneration.
8. Archive reflections:
   - run `python3 -m phase_loop_runtime.reflection_corpus archive --manifest <corpus_manifest>`, adding `--exclude <path>` for every reflection supporting a failed recommendation; it moves each consumed file to `archive/` under the same repo and branch subtree;
   - the manifest decides what is consumed: the admitted reflections of ready skills, plus reflections excluded as a duplicate (`duplicate_of`) or with no friction and no proposal (`no_friction_or_proposal`);
   - all other reflections stay in place, including those excluded as repo-specific, capped or oversized and those of skills still below the threshold, so their friction can count in a later pass.

## Failure Policy

- Malformed plan: stop and report exact parse failure.
- Missing target skill: mark that recommendation failed; continue only if other independent targets remain.
- Patch conflict: re-read the file, adjust once, then report if still blocked.
- Validation failure: fix if local to the edit; otherwise roll forward with a clear report and do not archive affected reflections.

## Closeout

Closeout payload shape is defined by `EmitPhaseCloseout` in `phase_loop_runtime/baml_src/emit_phase_closeout.baml` (if that path is absent in the checkout, use the operator/prompt-supplied field contract or the installed `phase_loop_runtime` package — the missing vendored BAML source is not a blocker); keep skill text focused on value selection and handoff routing, not duplicated field ceremony.

Report:

- applied recommendations;
- skipped or failed recommendations;
- files changed;
- reflections archived;
- validation commands run.

If writing self-improvement state, resolve handoff writes through `shared/phase-loop/handoff_path.py` and the repo-local handoff resolver; legacy harness handoff roots are read only for migration. Follow the repo/branch/run-isolated layout from `phase_loop_runtime.skill_paths` and use Harness paths only:

- Reflection: `resolve_skill_bundle_root("gemini")/<harness>-skill-editor/reflections/<repo_hash>/<branch_slug>/<run_id>.md`
- Handoff: `<repo>/.dev-skills/handoffs/<harness>-skill-editor/<run_id>.md`
- Latest handoff pointer: `<repo>/.dev-skills/handoffs/<harness>-skill-editor/latest.md`

Handoff frontmatter must include `from: <harness>-skill-editor`, `timestamp:`, `repo:`, `repo_root:`, `branch:`, `branch_slug:`, `commit:`, `run_id:`, and `artifact:`. Update `latest.md` with the same handoff content.
