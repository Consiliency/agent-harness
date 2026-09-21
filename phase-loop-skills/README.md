# phase-loop-skills

The harness-neutral workflow-skills bundle for the phase-loop runtime. Each top-level
directory is one workflow skill, authored once and installed with a per-harness prefix
(`claude-`, `codex-`, `gemini-`, `opencode-`) into that harness's skill root.

## The skills

| Skill | What it does |
|---|---|
| `advisor-board` | Run the runtime-owned customizable cross-vendor advisor board (formerly `advisor-panel`, still a working alias) over high-stakes review artifacts |
| `phase-roadmap-builder` | Turn a plan/conversation into a phased `specs/phase-plans-v<N>.md` roadmap |
| `plan-phase` | Architect one phase into parallel swim-lanes with frozen interfaces |
| `execute-phase` | Run a phase's lanes to completion — the main harness thread by default; parallel workers and merge each require explicit authorization |
| `plan-detailed` | Plan a single bounded change, no roadmap overhead |
| `execute-detailed` | Execute a bounded plan produced by `plan-detailed` |
| `run-train` | Drive a cross-repo release train across dependent nodes |
| `task-contextualizer` | Brief a subagent with the file paths and architecture it needs |
| `phase-loop` | Drive the roadmap → plan → execute loop end-to-end |
| `skill-editor` | Author/edit a skill |
| `skill-improvement-planner` | Plan improvements to a skill from reflections |

## Layout

```
phase-loop-skills/
  <skill>/
    SKILL.md                    # the base (harness-neutral) skill
    _overrides/<harness>/       # optional per-harness overlay (claude|codex|gemini|opencode)
```

The base `SKILL.md` is shared; `_overrides/<harness>/` files replace or augment it for a
specific harness at install time. Author skill changes in `skills-src/`; the skill
subdirectories are generated from those sources, then synchronized into the runtime's
packaged bundle. This top-level README is maintained here, not emitted by the generator.

## Install

Use the runtime's installer (it resolves the per-harness prefix + skill root):

```sh
phase-loop install --harness claude --source <path-to>/phase-loop-skills --copy --dry-run
phase-loop install --harness claude --source <path-to>/phase-loop-skills --copy --apply
```

Or just run the repo's `install-agent-harness.sh --harness <h>`, which installs the
runtime and these skills together. Default skill roots: `~/.claude/skills`,
`~/.codex/skills`, `~/.gemini/skills`, `~/.config/opencode/skills`.

Copy installation replaces the listed managed directories; back up local edits
before applying. See [Team onboarding](../docs/TEAM-ONBOARDING.md) for setup checks,
governance choices and known limitations in installed paths for non-Codex skills.
