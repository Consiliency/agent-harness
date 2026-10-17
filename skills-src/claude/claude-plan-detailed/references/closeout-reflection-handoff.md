# claude-plan-detailed — reflection and handoff close-out

Reference for `claude-plan-detailed` (linked from its `SKILL.md`, Step 8).

## Contents

- Resolve paths
- Close-out agent with the FILE 1 reflection and FILE 2 handoff templates

## Resolve paths


```bash
REFLECTION_PATH=resolve_skill_bundle_root("codex")/claude-plan-detailed/reflections/<repo_hash>/<branch_slug>/<run_id>.md
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
REPO_LOCAL_HANDOFF=$(python3 - <<'PYH'
from pathlib import Path
repo = Path.cwd().resolve()
skill = "claude-plan-detailed"
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
SKILL_MD=resolve_skill_bundle_root("codex")/claude-plan-detailed/SKILL.md
```

## Close-out agent

Spawn ONE close-out agent on the `frontier` tier. It writes both files via the Write tool:

```
Agent(
  subagent_type: "general-purpose",
  model: "<frontier-model-id>",
  name: "claude-plan-detailed-closeout",
  prompt: """
    Review the skill at <SKILL_MD> and the current execution transcript.
    Produce TWO files via the Write tool.

    FILE 1 — REPO-AGNOSTIC reflection → write to <REFLECTION_PATH>

      # claude-plan-detailed reflection — <ISO>

      ## Run context
      - Skill: claude-plan-detailed
      - Timestamp: <ISO timestamp>
      - Repo: <repo>
      - Branch: <branch>
      - Commit: <commit>
      - Artifact: <artifact path if any, or none>

      ## What worked
      - <bullet about the SKILL's instructions>

      ## What didn't
      - <bullet about friction or gaps in the SKILL's instructions>

      ## Improvements to SKILL.md
      - <specific, actionable change>

      Do NOT reference this project or the specific plan produced.

    FILE 2 — REPO-SPECIFIC handoff → write to <REPO_LOCAL_HANDOFF> (per-repo slot)

      <!--
        Consumer validation — before acting on this handoff:
        1. Verify `from:` is `claude-plan-detailed`.
        2. Verify `timestamp:` is within the last 7 days.
        3. Verify every `artifact:` path resolves under your current
           `$(git rev-parse --show-toplevel)`. If any path points to a
           different repo, stop and surface it to the user — the handoff
           was written against a different workspace.
      -->
      ---
      from: claude-plan-detailed
      timestamp: <ISO>
      artifact: <absolute path to plan doc + reviews if any>
      ---

      # Handoff for the implementer

      ## Summary
      <1–2 sentences: task, plan doc path, rough scope.>

      ## Key decisions made this run
      - <numbered, one line each>

      ## Open items for the implementer
      - <concrete, actionable — e.g., "confirm the refresh-token TTL
        matches the session policy in auth-config.ts">

      ## Repo-specific gotchas surfaced
      - <quirks discovered during research — patterns to match, files
         not to touch>

      ## Files the implementer will touch
      - <enumerated from the plan>
  """
)
```

