---
name: claude-skill-improvement-planner
description: "Claude Code skill feedback aggregator. Reads workflow skill reflections, groups recurring recommendations, and writes an improvement plan for claude-skill-editor."
---

# claude-skill-improvement-planner

## Runtime State

For reflections, handoffs, and latest handoff pointers, follow the repo/branch/run-isolated layout from `phase_loop_runtime.skill_paths`. That contract supersedes any older flat closeout examples retained for historical context in this skill.

Reads reflection files produced by every workflow skill's close-out step — plus reflections emitted by the meta-skills (`claude-skill-improvement-planner`, `claude-skill-editor`) themselves — aggregates recurring themes across runs, and writes an improvement plan. Does not edit skills. A separate `claude-skill-editor` skill ingests the plan and performs the edits. Including the meta-skills' own reflections closes the self-improvement loop so this planner and the editor can be iterated on with the same pipeline they drive.

## Pipeline

Canonical source for every `claude-*` workflow skill is `skills-src/claude/claude-<skill>/SKILL.md` in the agent-harness checkout (IF-0-CANON-1, `docs/phase-loop/skills-canonical-source.md`):

1. Canonical source: `skills-src/claude/claude-<skill>/` (edit here).
2. Generated bundle: `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py` → `phase-loop-skills/`, then `python3 phase-loop-runtime/scripts/sync_skills_bundle.py` → packaged `skills_bundle/`.
3. Installed runtime roots: `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`, and `~/.config/opencode/skills/`.

Name target files under `skills-src/` only; generated and installed copies are never the source of truth.

## When to use

- The user wants to audit accumulated reflections and decide what to change.
- Several phases have executed; reflections have built up at `resolve_skill_bundle_root("claude")/<skill>/reflections/`.
- The user asks about updating skills based on past runs.

## When NOT to use

- User wants to edit a skill directly — they want `/claude-skill-editor` (once it exists) or manual edits.
- No reflections exist yet — the skill will exit with a user-facing message.

## Inputs

| Arg | Required | Meaning |
|---|---|---|
| `--target <skill-name>` | no | Plan only for one skill; skip the rest. Default: every in-scope skill (Step 1). |
| `--corpus <dir>` | no | A collector output directory (`bundle.md` + `manifest.json`). Default: run the collector in Step 1. |
| `--min-reflections <N>` | no | Default 2. Skip skills with fewer new (un-archived) reflections to avoid acting on noise. |
| `--output <path>` | no | Override the generated plan path. |

## Workflow

### Step 1 — Collect the corpus

Do not hand-glob. Run the collector, which scans every harness skill root (reflections from all harnesses land under `~/.codex/skills/` and `~/.claude/skills/`), excludes `archive/`, and applies the capture quality filter:

```bash
python3 -m phase_loop_runtime.reflection_corpus collect --out-dir <dir> --min-reflections <N>
```

It writes `<dir>/bundle.md` (the aggregator input, grouped by bare skill) and `<dir>/manifest.json` (`reflections_consumed`, per-reflection exclusions, `ready_skills`). In scope, for every harness prefix:

- `claude-phase-roadmap-builder`
- `claude-plan-phase`
- `claude-execute-phase`
- `claude-plan-detailed`
- `claude-execute-detailed`
- `claude-task-contextualizer`
- `claude-skill-improvement-planner`
- `claude-skill-editor`
- `claude-advisor-board`
- `claude-phase-loop`
- `claude-run-train`

`advisor-panel` reflections count as `advisor-board`. The meta-skills close the self-improvement loop: this planner and the editor write reflections on their own runs, and those must be aggregated here or the meta-skills can never be improved by their own pipeline.

The quality filter drops exact and near-duplicate reflections, strips lines repeated across reflections (boilerplate), redacts closeout-ledger detail (paths, URLs, SHAs, issue refs), rejects reflections whose `Improvements` are repo-specific, drops reflections with neither friction nor a proposal, and caps reflections per repo/branch. Every exclusion and its reason is in the manifest.

If `--target <skill>` is set, limit aggregation to that skill.

### Step 2 — Read the parse

Each bundle entry carries its manifest id (`R0001`), skill and timestamp, and the sections `What worked`, `What didn't` (also headed `What did not`), and `Improvements to SKILL.md`. Entries without those headings are tagged `unstructured`. `What didn't` is the primary friction evidence; a recommendation may rest on it alone.

### Step 3 — Gate on minimum

- Admitted reflections = 0 → print "No reflections to aggregate: none written, all archived, or all filtered (see manifest exclusions)." Exit 0.
- Skills absent from manifest `ready_skills` → skip; note in the plan summary.

### Step 4 — Aggregate via frontier-tier Agent

Resolve the `frontier` tier from `claude-execute-phase`'s Model tiers table. Spawn one Agent:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "skill-improvement-aggregator",
  prompt: <contents of assets/aggregator_prompt.md>
        + "\n\n" + <contents of <dir>/bundle.md>
)
```

When the bundle exceeds one context, spawn one aggregator per skill section, then one cross-cutting pass over their outputs.

The aggregator prompt (in `assets/aggregator_prompt.md`) instructs the Agent to:

- Identify recurring themes (≥ `--min-reflections` distinct reflections per skill, or ≥ 2 across skills for cross-cutting).
- Separate high-confidence actionable from speculative one-offs.
- Flag contradictions.
- Propose concrete SKILL.md edits in directive-only style.
- Enforce repo-agnostic output — reject or rewrite any recommendation that names a specific project, codebase, domain, or filename.
- Apply the already-covered, decision-changing and structural-mechanism admission gates.
- Cite supporting manifest ids per theme.

### Step 5 — Write the plan file

Resolve the next plan path:

```bash
N=$(ls resolve_skill_bundle_root("claude")/claude-skill-improvement-planner/plans/ 2>/dev/null | grep -c '^plan-v')
PLAN_PATH=resolve_skill_bundle_root("claude")/claude-skill-improvement-planner/plans/plan-v$((N+1))-$(date -u +%Y%m%dT%H%M%SZ).md
```

Write the plan using the template in `## Plan file format` below. Copy the manifest's `reflections_consumed` into the frontmatter and record `corpus_manifest:` — this is how the downstream claude-skill-editor knows what to archive.

### Step 6 — Close-out (standard artifact-producing pattern)

No cleanup commit needed (plans/ is gitignored; no other files changed). Verify `git status` clean with the allowlist `plans/` and exit.

Resolve close-out paths:

```bash
REFLECTION_PATH=$(python3 resolve_skill_bundle_root("claude")/_shared/next_reflection_path.py claude-skill-improvement-planner)
REPO_LOCAL_HANDOFF=<repo>/.dev-skills/handoffs/claude-skill-improvement-planner/latest.md
SKILL_MD=resolve_skill_bundle_root("claude")/claude-skill-improvement-planner/SKILL.md
```

Spawn ONE close-out agent on the `frontier` tier. It writes both files directly via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "claude-skill-improvement-planner-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # claude-skill-improvement-planner reflection — <ISO>

      ## What worked
      - <bullet about the SKILL's instructions>

      ## What didn't
      - <friction the SKILL's instructions caused or failed to prevent>

      ## Improvements to SKILL.md
      - <specific, actionable change, or "None.">

      Do NOT reference this project or the specific reflections aggregated
      this run.

    FILE 2 — REPO-SPECIFIC handoff → write to <REPO_LOCAL_HANDOFF>

      ---
      from: claude-skill-improvement-planner
      timestamp: <ISO>
      artifact: <absolute path to plan file>
      ---

      # Handoff for claude-skill-editor

      ## Summary
      <1–2 sentences: plan path, how many reflections aggregated,
       how many recommendations produced>

      ## Key decisions made this run
      - <what themes were promoted vs deferred>

      ## Open items for claude-skill-editor
      - <read the plan at <path>; apply recommendations in order;
         archive consumed reflections per the plan's directive>

      ## Files to watch for claude-skill-editor
      - <target SKILL.md files named in the plan>
  """
)
```

Exit message to user:

> Plan written to `<PLAN_PATH>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<REPO_LOCAL_HANDOFF>`.
>
> Recommended next step: run `/clear`, then invoke `/claude-skill-editor <PLAN_PATH>`. The editor will apply the recommendations and archive the reflections this plan consumed. If `/claude-skill-editor` isn't installed yet, the plan is still readable and actionable by hand.

## Plan file format

```markdown
---
from: claude-skill-improvement-planner
timestamp: <ISO>
min_reflections: <N>
corpus_manifest: /absolute/path/to/manifest.json
reflections_consumed:
  - /absolute/path/to/reflection1.md
  - /absolute/path/to/reflection2.md
  - …
---

# Skill improvement plan — <ISO>

## Summary
<1–2 paragraphs: reflections read, skills covered, headline themes, contradictions surfaced.>

## Recommendations by skill

### <skill-name>
- **Change**: <specific SKILL.md edit, directive-only imperative form>
  - **Rationale**: <recurring theme this addresses>
  - **Target**: `skills-src/claude/claude-<skill>/SKILL.md`
  - **Supporting reflections**: R0012, R0040, R0101
- …

(Repeat per skill. If a skill had no actionable themes, write: "No recurring themes above the `--min-reflections` threshold.")

## Cross-cutting recommendations
<themes that affect multiple skills at once>

## Mechanism candidates
<themes better enforced by a check than by prose; route each to a filed issue, not a SKILL.md edit>

## Speculative / low-confidence notes
<one-off feedback worth recording but not acting on yet>

## Contradictions surfaced
<reflections that disagreed; surface for user judgment>

## Archival directive for claude-skill-editor

After applying the recommendations above, run `python3 -m phase_loop_runtime.reflection_corpus archive --manifest <corpus_manifest>`, adding `--exclude <path>` for each reflection that supports a failed recommendation. It moves each file listed under `reflections_consumed` to `<reflections-dir>/archive/<original-filename>`. This prevents re-aggregating the same feedback next cycle. If a specific recommendation fails to apply, leave its supporting reflections in place so the next planning pass can reconsider them.
```

## Archive convention

New convention introduced by this skill (the downstream editor performs the move):

- Path: `resolve_skill_bundle_root("claude")/<skill>/reflections/<repo_hash>/<branch_slug>/archive/<original-filename>`
- Directory created lazily on first archive.
- The collector excludes `archive/` when scanning.
- Reflections live only in installed runtime roots, never in `skills-src/`.

## Best practices followed

- Directive-only: imperative form, no narratives, no stats.
- Progressive disclosure: the long aggregator prompt lives in `assets/aggregator_prompt.md`, not inline.
- Close-out pattern matches the pipeline skills so this skill's own corpus feeds future self-improvement passes.
- Repo-agnostic enforcement is load-bearing — aggregated reflections drive changes to SKILL.md files that ship to every repo, so any repo-specific leakage would propagate.

## Reference files

- `assets/aggregator_prompt.md` — the full prompt given to the aggregation Agent.


Use `phase_loop_runtime.skill_paths` resolver helpers for harness skill roots, handoff roots, helper roots, and reflection roots.

## Closeout

Closeout payload shape is defined by `EmitPhaseCloseout` in `phase_loop_runtime/baml_src/emit_phase_closeout.baml` (if that path is absent in the checkout, use the operator/prompt-supplied field contract or the installed `phase_loop_runtime` package — the missing vendored BAML source is not a blocker); keep skill text focused on value selection and handoff routing, not duplicated field ceremony.
