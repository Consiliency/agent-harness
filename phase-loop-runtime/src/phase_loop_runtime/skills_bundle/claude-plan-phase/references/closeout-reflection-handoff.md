# claude-plan-phase — reflection and handoff close-out

Reference for `claude-plan-phase` (linked from its `SKILL.md`, section
`Close-out — Reflection + Handoff`). Interactive runs only: adapter mode must
not write `~/.claude/**` reflection or handoff files.

## Contents

- Resolve paths
- FILE 1 — reflection template
- FILE 2 — repo-local handoff template
- Optional close-out agent
- Final message to the user

## Resolve paths

After artifacts are staged or confirmed tracked, resolve paths. Treat `_shared/next_reflection_path.py` as optional-if-present: check existence, use it when available, otherwise fall back to an inline date-based filename.

```bash
REFLECTION_PATH=resolve_skill_bundle_root("codex")/claude-plan-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
REPO_LOCAL_HANDOFF=$(python3 - <<'PYH'
from pathlib import Path
repo = Path.cwd().resolve()
skill = "claude-plan-phase"
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
SKILL_MD=resolve_skill_bundle_root("codex")/claude-plan-phase/SKILL.md
```

Primary path: the orchestrator writes BOTH files directly with the Write tool. Before writing either file, ensure the plan doc has been staged in the preceding Close-out "Stage artifact" section unless the user explicitly forbade staging.

## FILE 1 — reflection template

FILE 1 — REPO-AGNOSTIC reflection → `<REFLECTION_PATH>`:

```markdown
# claude-plan-phase reflection — <ISO timestamp>

## Run context
- Skill: claude-plan-phase
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

## FILE 2 — repo-local handoff template

FILE 2 — REPO-SPECIFIC handoff → `<REPO_LOCAL_HANDOFF>` (per-repo slot; overwrites any prior handoff from this skill in the same repo):

```markdown
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
from: claude-plan-phase
timestamp: <ISO>
artifact: <absolute path to plan doc + reviews if any>
artifact_state: <staged|tracked|modified|unstaged|blocked>
next_skill: <claude-execute-phase|none>
next_command: </claude-execute-phase PHASE_ALIAS|none - reason>
next_phase: <PHASE_ALIAS - execution ready|PHASE_ALIAS - blocked: reason>
---

# Handoff for claude-execute-phase

## Summary
<2-3 sentences: phase planned, lanes count, plan doc path.>

## Key decisions made this run
- <numbered, one line each — lane boundaries, IF-freeze signatures, consensus outcomes if --consensus was used>

## Open items for claude-execute-phase
- <concrete — e.g., "SL-2 depends on SL-1's StoreRegistry.get signature; ensure lane ordering in dispatch">

## Repo-specific gotchas surfaced
- <quirks of THIS codebase discovered during planning>

## Planning artifacts staged this run
- <path> @ <artifact_state>

## Execute-phase's likely scope
- <file globs from Owned files across lanes>
```

## Optional close-out agent

Optional alternative: when fresh-context independent review is desired, the orchestrator MAY instead spawn ONE close-out agent using the `frontier` tier with the prompt below. Use this only when the orchestrator wants a clean-context review of the transcript before writing.

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "claude-plan-phase-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce the two files above (same schemas) via the Write tool to
    <REFLECTION_PATH> and <REPO_LOCAL_HANDOFF>.
  """
)
```

## Final message to the user

After the files are written, print to the user:

> Plan written to `<plan-doc-path>`.
> Reflection saved to `<REFLECTION_PATH>`.
> Handoff written to `<REPO_LOCAL_HANDOFF>`.
>
> Recommended next step: run `/clear` to reset your context window, then invoke `/claude-execute-phase <alias>`. The next skill reads the handoff automatically.
