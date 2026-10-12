# claude-plan-phase — interactive workflow detail

Reference for `claude-plan-phase` (linked from its `SKILL.md`). Phase-loop
adapter mode does not use any of this: it forbids handoff reads, teammates,
`TaskCreate`, `ExitPlanMode`, `advisor()` and `AskUserQuestion`.

## Contents

- Step 0 — Predecessor handoff paths and checks
- Step 2 — Explore teammate brief
- Step 3 — Consensus framings
- Consensus mechanism (synthesis rule)
- Step 7.5 — External CLI review
- Manual hand-off (when `claude-execute-phase` is unavailable)

## Step 0 — Predecessor handoff paths and checks

Handoffs are keyed on the current repo so each workspace has its own slot. Resolve both candidate paths first:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  REPO_KEY="_no-git-$(pwd | sha1sum | cut -c1-12)"
else
  REPO_KEY="$(basename "$REPO_ROOT")-$(printf '%s' "$REPO_ROOT" | sha1sum | cut -c1-12)"
fi
ROADMAP_HANDOFF="$(python3 - <<'PYH'
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
)"
EXECUTE_HANDOFF="$(python3 - <<'PYH'
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

The predecessor skill may be either:

- `claude-phase-roadmap-builder` (first time planning a phase against a new roadmap) → `$ROADMAP_HANDOFF`
- `claude-execute-phase` (planning the next phase after a prior one finished executing) → `$EXECUTE_HANDOFF`

Check both paths. If both exist, pick the one with the newer `timestamp:` in its metadata header. If only one exists, use it. If neither, proceed standalone.

Defense-in-depth checks (the repo-key scheme prevents the common cross-project case, but these still catch symlink-shared workspaces, manual file copies, and stale handoffs):

- `from:` must match the expected predecessor.
- Timestamp must be recent (<7 days).
- Every `artifact:` path must resolve under `$(git rev-parse --show-toplevel)`.

On any failure, flag via `AskUserQuestion` with `[use anyway, ignore, abort]`.

Fold the handoff's "Open items" and "Repo-specific gotchas" into the brief given to Step 2's Explore teammates so they know what to watch for.

## Step 2 — Explore teammate brief

Preflight: call `TeamDelete` defensively to flush any inherited team context from a predecessor skill run, then `TeamCreate` a fresh team named for this run before dispatching any `Agent` calls. Recognize these error signatures as benign on the `TeamDelete`: `Team X does not exist` or `already leading team X`.

Launch up to 3 `Agent(subagent_type: "Explore")` calls in a single message. One per major area the phase touches. Each Agent call MUST set `name:` so it can be re-addressed later via `SendMessage`.

Teammate-naming template: `explore-<area>` (e.g., `explore-schema`, `explore-workers`).

Each brief must include:

- The phase's Objective + Exit criteria copied verbatim from the spec.
- A scoped question: "Map existing code in `<paths>` relevant to this phase. Surface: (a) existing utilities/patterns to reuse, (b) current type/schema/interface shapes that constrain the design, (c) places that will need to change, (d) hidden coupling that would break worktree isolation."
- A 1–2 sentence architecture context: how these paths fit the larger system.
- Related files the teammate should know about but not rewrite (type defs, tests, shared config).
- A preload instruction: "Load `SendMessage` via `ToolSearch(query: \"select:SendMessage\")` as your first action so you can reply without a round-trip."
- An explicit deliverable statement: "Your deliverable is a `SendMessage` to team-lead with your findings; do not rely on text output or idle without reporting."
- A length guideline: "Be as short as possible while citing every load-bearing file:line. No fixed word cap."

Apply the `/claude-task-contextualizer` checklist to every brief.

Block until all return. Their findings populate `## Context`.

## Step 3 — Consensus framings

**With `--consensus`**: Launch 2–3 `Agent(subagent_type: "Plan")` calls in a single message, each with a distinct framing:

| Name | Framing |
|---|---|
| `arch-minimal` | Minimal change. Preserve current module boundaries. Add, don't refactor. |
| `arch-clean` | Clean architecture. Willing to refactor to make the design right. |
| `arch-parallel` | Maximize parallelism. Prefer more, smaller lanes over fewer, fatter lanes, even if it adds interface surface. |

Each teammate's brief includes: the spec phase section, all Explore teammate findings, and its framing. Apply the `/claude-task-contextualizer` checklist — architecture context and related-files list carry over from the Explore briefs. Each must return: (1) proposed interface freezes, (2) proposed lane decomposition with file ownership, (3) rationale, (4) known risks.

Synthesize per the Consensus mechanism below. If round 1 doesn't converge, re-address the same named teammates via `SendMessage` (not new `Agent` calls) with the specific disagreement surfaced. Max 2 rounds.

**Without `--consensus`**: Launch 1 `Agent(subagent_type: "Plan", name: "arch-baseline")` for baseline architecture decisions.

## Consensus mechanism (synthesis rule)

Applied by the main thread after `--consensus` Step 3a:

1. **Unanimous** across all teammates → accept directly.
2. **Majority (2 of 3)** → accept the majority view; record the dissenting view under `## Execution Notes > Architectural choices > Dissent`.
3. **No majority** → re-address the same named teammates via `SendMessage` with the specific conflict surfaced. Max 1 additional round.
4. **Still no convergence** → main thread picks (biased toward `arch-parallel` for this skill's purpose) and records the full disagreement under `## Execution Notes > Unresolved architectural disagreements`.

## Step 7.5 — External CLI review

Run the shared review script:

```bash
python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/review_with_cli.py" \
  --artifact plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md \
  --prompt-file "$(git rev-parse --show-toplevel)/.claude/skills/claude-plan-phase/assets/review_prompt.md" \
  --out plans/phase-plan-<VERSION>-<PHASE_ALIAS>_reviews.md
```

If the script reports the frontier-model cache is empty, it prints a discovery prompt to stderr. Surface to the user via `AskUserQuestion` with options `[run discovery now, skip review this run, abort]`.

Tell the user: "Review written to `plans/phase-plan-<VERSION>-<PHASE_ALIAS>_reviews.md`. When Gemini and Codex flag the same concern, treat it as real; divergent comments are context, not verdicts."

## Manual hand-off (when `claude-execute-phase` is unavailable)

Run `python scripts/validate_plan_doc.py <plan-doc-path>` first. Then execute each lane in one of two ways:

- (a) **Standalone** — `Agent(isolation: "worktree", name: "<SL-ID>", subagent_type: "general-purpose")` without `team_name`. The `isolation` kwarg is honored in this form; loses team coordination.
- (b) **Teamed** — `TeamCreate` + `Agent(team_name=…, name="<SL-ID>", subagent_type="general-purpose")`, and the teammate's first tool call is `EnterWorktree` (load via `ToolSearch(query="select:EnterWorktree")`). Worktree via tool, team coordination preserved.
