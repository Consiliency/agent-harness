---
name: skill-editor
description: "Claude Code skill editor. Applies plans from <harness>-skill-improvement-planner, updates targeted skills, and archives consumed reflections after successful edits."
---

# <harness>-skill-editor

## Runtime State

For reflections, handoffs, and latest handoff pointers, follow the repo/branch/run-isolated layout from `phase_loop_runtime.skill_paths`. That contract supersedes any older flat closeout examples retained for historical context in this skill.

Applies the plan produced by `<harness>-skill-improvement-planner` to the target SKILL.md files. Interprets each recommendation, edits the canonical source, regenerates the bundle, and archives the reflections the plan consumed so they won't drive another pass.

## Pipeline

Canonical source for every `<harness>-*` workflow skill is `skills-src/claude/<harness>-<skill>/SKILL.md` in the agent-harness checkout (IF-0-CANON-1, `docs/phase-loop/skills-canonical-source.md`):

1. Canonical source: `skills-src/claude/<harness>-<skill>/` (edit here, nowhere else).
2. Generated bundle: `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py` → `phase-loop-skills/`, then `python3 phase-loop-runtime/scripts/sync_skills_bundle.py` → packaged `skills_bundle/`. A hand edit to a generated copy fails the parity gate.
3. Installed runtime roots: `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`, and `~/.config/opencode/skills/`.

## When to use

- Right after a `<harness>-skill-improvement-planner` run. Its handoff points here.
- The user names a plan file explicitly and wants it applied.

## When NOT to use

- No plan file exists → run `/<harness>-skill-improvement-planner` first.
- User wants to edit a skill's instructions by hand → this skill is for applying a structured plan, not arbitrary edits.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `<plan-path>` | no | Absolute path to a plan produced by `<harness>-skill-improvement-planner`. Default: read `resolve_skill_bundle_root("claude")/<harness>-skill-improvement-planner/latest.md`'s `artifact:` field. |
| `--dry-run` | no | Parse the plan and print what WOULD change without editing any files. |
| `--no-push` | no | Commit but skip `git push`. Default: push the feature branch. |

## Workflow

### Step 0 — Resolve plan path

If `<plan-path>` passed, use it verbatim.

Else read `resolve_skill_bundle_root("claude")/<harness>-skill-improvement-planner/latest.md`:

- Validate YAML frontmatter `from: <harness>-skill-improvement-planner`. On mismatch → flag via `AskUserQuestion` with `[use anyway, provide plan path, abort]`.
- Validate timestamp < 7 days old. On staleness → same AskUserQuestion.
- Extract `artifact:` → this is the plan path.

If neither source yields a path, stop and ask the user to provide one via `AskUserQuestion`.

### Step 1 — Parse the plan

Read the plan file. Extract:

- **Frontmatter** — YAML block at top. Fields:
  - `from: <harness>-skill-improvement-planner` (validate)
  - `timestamp:`
  - `min_reflections:`
  - `corpus_manifest:` — the collector manifest the archive step reads
  - `reflections_consumed:` — list of absolute paths (this is the archival worklist)
- **Recommendations per skill** — `### <skill-name>` subheadings under `## Recommendations by skill`. For each subheading, collect every `**Change**:` bullet with its `**Rationale**:`, `**Target**:` and `**Supporting reflections**:` lines.
- **Cross-cutting recommendations** — same structure under `## Cross-cutting recommendations`; these name multiple skills each.
- **Speculative / low-confidence notes** — record but do not act on.
- **Contradictions surfaced** — record and print to user; do not auto-resolve. If contradictions exist, surface before applying and offer to skip affected recommendations.

Build a per-skill work list. Each entry: `(skill_name, change_text, rationale, supporting_reflection_versions)`.

### Step 2 — Validate

- Every `reflections_consumed` path exists on disk. If any are missing → warn the user; skip them for archival but continue with edits.
- Every target skill named in recommendations has a canonical SKILL.md at `skills-src/claude/<harness>-<skill>/SKILL.md` under the agent-harness checkout. If missing → fail that recommendation and note it in the outcome report; never edit an installed or generated copy instead.
- Detect double-application: if the plan's timestamp is already recorded in `resolve_skill_bundle_root("claude")/<harness>-skill-editor/applied-plans.log`, ask via `AskUserQuestion` with `[apply again, abort]` — applying twice is usually wrong.

On `--dry-run`, skip to Step 7 (print the worklist and exit).

### Step 3 — Apply recommendations (per-recommendation frontier-tier Agent)

For each recommendation, spawn an Agent to apply it. Resolve `<frontier>` from the `<harness>-execute-phase` Model tiers table.

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "<harness>-skill-editor-<skill>-<seq>",
  prompt: <contents of assets/editor_prompt.md>
        + "\n\n# Target skill\n<skill-name>"
        + "\n\n# Target SKILL.md path\n<absolute path>"
        + "\n\n# Change to apply\n<change text>"
        + "\n\n# Rationale\n<rationale text>"
)
```

The Agent has Read/Edit/Write tools. It reads the target SKILL.md, applies the specified change in directive-only style (preserving house style), and reports outcome JSON: `{applied: bool, files_modified: [path], diff_summary: "...", error: "..."}`.

Track per-recommendation outcomes. Don't stop on individual failures — collect them all for the final report.

Dispatch in parallel where safe: multiple recommendations targeting different skills can run concurrently. Multiple recommendations targeting the **same** skill must serialize (sequential Edit calls to the same file can conflict).

### Step 4 — Regenerate and gate

From the agent-harness checkout root:

```bash
python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py
python3 phase-loop-runtime/scripts/sync_skills_bundle.py
uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest \
  phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py -q
```

If either gate fails, treat every recommendation applied this run as failed for archival purposes.

### Step 5 — Archive consumed reflections

Per the plan's archival directive:

1. Collect the reflections cited (via `**Supporting reflections**`) by any recommendation that failed.
2. Archive everything else the manifest consumed:
   ```bash
   python3 -m phase_loop_runtime.reflection_corpus archive --manifest <corpus_manifest> \
     --exclude <path-cited-by-a-failed-recommendation> ...
   ```
   Run it with `--dry-run` first and check the count.
3. Excluded paths stay in place so the next cycle can reconsider them.

The manifest decides what is consumed: the admitted reflections of ready skills, plus reflections excluded as a duplicate (`duplicate_of`) or with no friction and no proposal (`no_friction_or_proposal`). All other reflections stay in place, including those excluded as repo-specific, capped or oversized and those of skills still below the threshold, so their friction can count in a later pass. An admitted reflection of a ready skill that no surviving recommendation cites is still archived; it has been considered.

### Step 6 — Commit + push

Commit in the agent-harness checkout on a feature branch, never on `main`:

```bash
git add skills-src/ phase-loop-skills/ phase-loop-runtime/src/phase_loop_runtime/skills_bundle/
git commit -m "chore(skills): apply improvement plan <plan-timestamp>

Applied N of M recommendations from <plan-path>. skills-src/ is the edit;
phase-loop-skills/ and skills_bundle/ are regenerated output. Consumed
reflections moved to each skill's reflections/<repo_hash>/<branch_slug>/archive/.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

`git push` the feature branch unless `--no-push`. Opening and merging the PR follow the repo's own review rules.

Append the plan's timestamp + path to `resolve_skill_bundle_root("claude")/<harness>-skill-editor/applied-plans.log` so Step 2's double-apply check has state to read.

### Step 7 — Close-out (standard pattern)

Resolve paths:

```bash
REFLECTION_PATH=$(python3 resolve_skill_bundle_root("claude")/_shared/next_reflection_path.py <harness>-skill-editor)
REPO_LOCAL_HANDOFF=<repo>/.dev-skills/handoffs/<harness>-skill-editor/latest.md
SKILL_MD=resolve_skill_bundle_root("claude")/<harness>-skill-editor/SKILL.md
```

Spawn ONE close-out agent on the `frontier` tier. It writes both files via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "<harness>-skill-editor-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # <harness>-skill-editor reflection — <ISO>

      ## What worked
      - <bullet about the SKILL's instructions>

      ## What didn't
      - <friction the SKILL's instructions caused or failed to prevent>

      ## Improvements to SKILL.md
      - <specific, actionable change, or "None.">

      Do NOT reference this project or the specific plan applied.

    FILE 2 — REPO-SPECIFIC handoff → write to <REPO_LOCAL_HANDOFF>

      ---
      from: <harness>-skill-editor
      timestamp: <ISO>
      artifact: <plan path that was applied>
      ---

      # Handoff

      ## Summary
      <applied N of M recommendations from the plan; archived K reflections.>

      ## Key decisions made this run
      - <which recommendations were skipped and why, e.g., contradictions
         surfaced, target skill missing, agent error>

      ## Files changed this run
      - <SKILL.md paths + commit SHAs>

      ## Next skill
      - Usually no immediate next skill — the pipeline has closed the loop.
        A new `/<harness>-phase-roadmap-builder` run will pick up the improved
        instructions naturally.
  """
)
```

Exit message to user:

> Applied `<N>` of `<M>` recommendations from `<plan-path>`.
> `<K>` reflections archived.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<REPO_LOCAL_HANDOFF>`.
> Bundle regenerated; parity and drift gates `<pass|fail>`.
>
> Recommended next step: run `/clear`. The improved skill instructions take effect on the next pipeline invocation.

## Failure policy

- **Agent can't apply an edit** → mark recommendation failed, preserve its supporting reflections, continue with others.
- **Target skill missing** → mark failed, preserve its reflections, continue.
- **Plan file malformed** → surface to user via `AskUserQuestion`, offer abort.
- **Contradictions in plan** → print both sides, ask user which (or neither) to apply, continue with the rest.
- **Commit or push fails** → report to user; leave the working tree as-is for inspection.

## Reference files

- `assets/editor_prompt.md` — the full prompt given to each edit Agent.


Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.

## Closeout

Closeout payload shape is defined by `EmitPhaseCloseout` in `phase_loop_runtime/baml_src/emit_phase_closeout.baml` (if that path is absent in the checkout, use the operator/prompt-supplied field contract or the installed `phase_loop_runtime` package — the missing vendored BAML source is not a blocker); keep skill text focused on value selection and handoff routing, not duplicated field ceremony.
