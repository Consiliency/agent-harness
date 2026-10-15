# claude-phase-roadmap-builder — handoff, review and close-out detail

Reference for `claude-phase-roadmap-builder` (linked from its `SKILL.md`).

## Contents

- Step 0 — Predecessor handoff path and checks
- Step 8.5 — External CLI review
- Close-out — Reflection + Handoff templates

## Step 0 — Predecessor handoff path and checks

Handoffs are keyed on the current repo so each workspace has its own slot. Resolve the predecessor path first:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  REPO_KEY="_no-git-$(pwd | sha1sum | cut -c1-12)"
else
  REPO_KEY="$(basename "$REPO_ROOT")-$(printf '%s' "$REPO_ROOT" | sha1sum | cut -c1-12)"
fi
PREDECESSOR_HANDOFF="$(python3 - <<'PYH'
from pathlib import Path
repo = Path.cwd().resolve()
skill = "claude-execute-phase"
try:
    # Primary: the installed phase_loop_runtime.skill_paths resolver.
    from phase_loop_runtime.skill_paths import resolve_handoff_root
    print(resolve_handoff_root(repo) / skill / "latest.md")
except Exception:
    # Fallback: the repo-local handoff_path.py mirror, only when the runtime is not importable.
    from importlib import util
    spec = util.spec_from_file_location("handoff_path", repo / "shared" / "phase-loop" / "handoff_path.py")
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print(mod.resolve_handoff_path(repo, skill))
PYH
)"
```

If `$PREDECESSOR_HANDOFF` exists, `Read` it in full — a prior `/claude-execute-phase` run may have left context useful for the next roadmap (completed phases, decisions made, gotchas discovered mid-execution). Treat its contents as additional input to Step 1.

Defense-in-depth checks (the repo-key scheme prevents the common cross-project case, but these still catch symlink-shared workspaces, manual file copies, and stale handoffs):

- If the handoff's `from:` field is not `claude-execute-phase` or its timestamp is older than 7 days, flag via `AskUserQuestion` with `[use anyway, ignore, abort]`.
- Parse the handoff's `artifact:` field and verify at least one referenced path resolves under `$(git rev-parse --show-toplevel)`. On mismatch, surface `AskUserQuestion` with `[use anyway, ignore, abort]`.

If absent, proceed — this run is standalone.
## Step 8.5 — External CLI review

Requires `_shared/review_with_cli.py` (see Prerequisites). After the roadmap is written and validated, run:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/review_with_cli.py" \
  --artifact <output-path> \
  --prompt-file "$(git rev-parse --show-toplevel)/.claude/skills/claude-phase-roadmap-builder/assets/review_prompt.md" \
  --out <output-path>_reviews.md
```

If the frontier-model cache is empty, the script prints the discovery prompt to stderr. Surface to the user via `AskUserQuestion` with options `[run discovery now, skip review this run, abort]`.

Tell the user: "Review written to `<output-path>_reviews.md`. Agreements between Gemini and Codex are real signal; divergences are context."
## Close-out — Reflection + Handoff templates

Stage the roadmap/plan artifacts before writing either close-out file so the deliverable is preserved in the index unless the user explicitly forbade staging.

After artifacts are staged or confirmed tracked, resolve paths:

```bash
REFLECTION_PATH=resolve_skill_bundle_root("codex")/claude-phase-roadmap-builder/reflections/<repo_hash>/<branch_slug>/<run_id>.md
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
REPO_LOCAL_HANDOFF=$(python3 - <<'PYH'
from pathlib import Path
repo = Path.cwd().resolve()
skill = "claude-phase-roadmap-builder"
try:
    # Primary: the installed phase_loop_runtime.skill_paths resolver.
    from phase_loop_runtime.skill_paths import resolve_handoff_root
    print(resolve_handoff_root(repo) / skill / "latest.md")
except Exception:
    # Fallback: the repo-local handoff_path.py mirror, only when the runtime is not importable.
    from importlib import util
    spec = util.spec_from_file_location("handoff_path", repo / "shared" / "phase-loop" / "handoff_path.py")
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print(mod.resolve_handoff_path(repo, skill))
PYH
)
mkdir -p "$(dirname "$REPO_LOCAL_HANDOFF")"
SKILL_MD=resolve_skill_bundle_root("codex")/claude-phase-roadmap-builder/SKILL.md
```

Write BOTH files directly via the Write tool — this is the primary path.

FILE 1 — REPO-AGNOSTIC reflection → write to `<REFLECTION_PATH>`

```
# claude-phase-roadmap-builder reflection — <ISO timestamp>

## Run context
- Skill: claude-phase-roadmap-builder
- Timestamp: <ISO timestamp>
- Repo: <repo>
- Branch: <branch>
- Commit: <commit>
- Artifact: <artifact path if any, or none>

## What worked
- <bullet, about the SKILL's instructions>

## What didn't
- <bullet, about friction or gaps in the SKILL's instructions>

## Improvements to SKILL.md
- <specific, actionable change to the instructions>
```

Do NOT reference this project, codebase, filenames, or domain in FILE 1. Feedback is about how the skill's instructions performed, for a future meta-skill that digests reflections across runs.

FILE 2 — REPO-SPECIFIC handoff → write to `<REPO_LOCAL_HANDOFF>` (per-repo slot; overwrites any prior handoff from this skill in the same repo)

```
<!--
  Consumer validation — before acting on this handoff:
  1. Verify `from:` matches the expected predecessor skill.
  2. Verify `timestamp:` is within the last 7 days.
  3. Verify every `artifact:` path resolves under your current
     `$(git rev-parse --show-toplevel)`. If any path points to a
     different repo, stop and surface it to the user — the handoff
     was written against a different workspace.
-->
---
from: claude-phase-roadmap-builder
timestamp: <ISO>
artifact: <absolute path(s) to roadmap spec + any reviews written>
artifact_state: <staged|tracked|modified|unstaged|blocked>
next_skill: <claude-plan-phase|none>
next_command: </claude-plan-phase ALIAS|none - reason>
next_phase: <ALIAS - phase name|none - reason>
---

# Handoff for the next skill

## Summary
<2-3 sentences: what was produced, where to find it.>

## Key decisions made this run
- <numbered, one line each>

## Open items for the next skill
- <concrete, actionable — e.g., "Lane SL-3 expects the
  plugins_for(repo_id) signature from IF-0-P3-1; verify it
  before planning P4">

## Repo-specific gotchas surfaced
- <things that surprised this run; quirks of THIS codebase>

## Planning artifacts staged this run
- <path> @ <artifact_state>

## Next skill's likely scope
- <best-effort forecast of which files/paths the next skill will touch>
```

Optionally delegate to a spawned frontier-tier Agent instead when independent review with a fresh context window is desired (e.g., after complex runs). Resolve the model via the `claude-execute-phase` Model tiers table:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "claude-phase-roadmap-builder-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Write FILE 1 to <REFLECTION_PATH> and FILE 2 to <REPO_LOCAL_HANDOFF> using
    the FILE 1 and FILE 2 templates in this reference file.
  """
)
```

After the files are written, print to the user:

> Roadmap written to `<spec-path>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<REPO_LOCAL_HANDOFF>`.
>
> Recommended next step: run `/clear` to reset your context window, then invoke `/claude-plan-phase <ALIAS>`. The next skill reads the handoff automatically.
