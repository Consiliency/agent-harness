# claude-execute-phase — Step 9.5 close-out: reflection and handoff

Reference for `claude-execute-phase` (linked from its `SKILL.md`). Read it at Step 9.5, before writing the reflection and handoff.

## Contents

- Step 9.5 — Close-out: Reflection + Handoff

## Step 9.5 — Close-out: Reflection + Handoff

Before close-out, run `git status --short -- <plan_path> <roadmap_path>` for every consumed or updated planning artifact. If any planning artifact is untracked or modified and the user did not explicitly forbid staging, run `git add <path>` for each artifact. Rerun status and report `Artifact state: staged|tracked|modified|unstaged|blocked` for each artifact. Do not commit unless the user explicitly asked for a commit. Repo-local handoff files are operational state: do not `git add` an ignored handoff alongside the plan artifact unless the plan's owned-files/allowlist explicitly includes the handoff directory; leave ignored handoffs ignored and exclude them from artifact-state reporting.

Determine the next step before final response and handoff:

- If the current phase is incomplete or verification failed, set `Next phase: <current alias> - blocked: <blocker>` and `Next command: none - <blocker>`.
- If another generated phase plan is ready, set `Next phase: <next alias> - execution ready` and `Next command: /claude-execute-phase <next-alias>`.
- If the roadmap has an unplanned ready phase, set `Next phase: <next alias> - planning ready` and `Next command: /claude-plan-phase <next-alias>`.
- If the roadmap needs extension, set `Next phase: none - roadmap extension needed` and `Next command: /claude-phase-roadmap-builder`.
- If all phases are complete, set `Next phase: none - roadmap complete` and `Next command: none - roadmap complete`.

Resolve paths, with an inline fallback for the reflection helper:

```bash
REFLECTION_PATH=resolve_skill_bundle_root("codex")/claude-execute-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
REPO_LOCAL_HANDOFF=$(python3 - <<'PYH'
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
)
mkdir -p "$(dirname "$REPO_LOCAL_HANDOFF")"
SKILL_MD=resolve_skill_bundle_root("codex")/claude-execute-phase/SKILL.md
```

**Primary path — orchestrator writes inline.** The orchestrator writes BOTH files directly via the Write tool using the schemas below. This is the default.

**Optional alternative.** The orchestrator MAY instead spawn a frontier-tier agent for fresh-context independent review. Use this only when independent review is desired.

FILE 1 — REPO-AGNOSTIC reflection → write to `<REFLECTION_PATH>`

```
# claude-execute-phase reflection — <ISO timestamp>

## Run context
- Skill: claude-execute-phase
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

Do NOT reference this project, codebase, filenames, or domain.

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
from: claude-execute-phase
timestamp: <ISO>
artifact: <phase alias that was executed, merge-commit SHAs>
artifact_state: <staged|tracked|modified|unstaged|blocked>
next_skill: <claude-execute-phase|claude-plan-phase|claude-phase-roadmap-builder|none>
next_command: </claude-execute-phase next-alias|/claude-plan-phase next-alias|/claude-phase-roadmap-builder|none - reason>
next_phase: <next alias - status|none - reason>
---

# Handoff for the next skill

The next skill in the chain is usually `/claude-plan-phase` for the
subsequent phase, or `/claude-phase-roadmap-builder` if the user is
appending new phases to the roadmap.

## Summary
<2-3 sentences: which phase completed, how many lanes merged,
final verification state.>

## Key decisions made this run
- <numbered, one line each — salvaged commits, retry outcomes,
  which lanes needed escalated models>

## Open items for the next skill
- <concrete — e.g., "Phase P2A is next; its Interfaces consumed
  list references IF-0-P1-1 which was frozen with signature X">

## Repo-specific gotchas surfaced
- <surprises this run: slow tests, flaky browser checks,
  unexpected module coupling, quirks worth knowing>

## Files committed this run
- <merge-commit SHAs, with lane ID and brief description>

## Planning artifacts staged this run
- <path> @ <artifact_state>

## Next skill's likely scope
- <forecast of what claude-plan-phase / claude-phase-roadmap-builder will touch next>
```
