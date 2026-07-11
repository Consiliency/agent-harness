### Changed — SKILLREF (phase-loop authoring-skill refinements)

Folded recurring, code-verified skill-reflection learnings into the phase-loop
authoring skills. All four harness sources (`claude`/`codex`/`gemini`/`opencode`)
were edited together and the neutral bundle regenerated + synced; skill-canon
parity, bundle drift, claude literal-lint, and the LaunchSpec golden all stay
green.

- **roadmap-builder "Validator Format Contract".** `phase-roadmap-builder`
  SKILL now documents the load-bearing formatting rules that
  `phase_loop_runtime.roadmap_lint` enforces by regex: the `[A-Za-z0-9]+` alias
  shape with no decoration after `(ALIAS)`, each `**Field**` label on its own
  line, bulleted lists / `- [ ]` checkboxes, the lane-count/partition hint
  (`decompose into N lanes` / `Single lane`), and the malformed-heading cascade
  (a bad heading drops the whole phase — fix the heading first, then re-run).

- **`phase_loop_runtime.skill_paths` resolver is now primary.** In
  `phase-roadmap-builder`, `plan-phase`, `plan-detailed`, and `execute-phase`,
  closeout/handoff resolution leads with the installed
  `phase_loop_runtime.skill_paths` resolver (`resolve_handoff_root`,
  `resolve_reflection_root`) and demotes the repo-local `handoff_path.py` mirror
  to a fallback used only when the runtime is not importable.

- **Skip-Explore-when-context-in-session + proportionality.** `plan-phase` and
  `plan-detailed` now tell the planner not to spawn Explore/reconnaissance
  subagents to re-gather context already in the session, and to keep
  reconnaissance proportional to the change size.

- **Multi-roadmap alias/create-mode note.** `phase-roadmap-builder` clarifies
  that each `specs/phase-plans-v*.md` is its own alias namespace and that a new
  initiative is a new roadmap (create mode), not an append onto the newest
  version.

- **Draft-PR-early protocol (re-homed here from PUSHFLOW).** `execute-phase`
  documents pushing the branch and opening a DRAFT PR on the first commit of a
  phase (visibility contract, not a merge request), respecting runner-owned
  publication in governed/autonomous mode. Homing it in SKILLREF keeps the
  execute-phase skill a single-writer surface for this run.

- **Reflection cache cleared.** These edits digest the recurring
  `~/.codex/skills/*/reflections/` learnings; that cache is cleared at phase
  closeout (after this branch merges, and only once no concurrent codex-harness
  run is mid-write) for a fresh post-0.7.0 start. This committed note is the
  durable record of that out-of-repo deletion.
