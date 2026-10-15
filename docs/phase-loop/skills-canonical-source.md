# Canonical phase-loop skill source (IF-0-CANON-1)

This note declares the **single canonical source** for the phase-loop workflow
skill pack and the **one-command regenerate** that produces the committed bundle
from it. It satisfies interface-freeze gate **IF-0-CANON-1** of the v50 skills
cutover (decision **A — agent-harness owns the skill sources**).

## Canonical source location

The authored skill *sources* live in this repository at:

```
skills-src/
  claude/    claude-<skill>/   (SKILL.md + scripts/ references/ assets/)
  codex/     codex-<skill>/
  gemini/    gemini-<skill>/
  opencode/  opencode-<skill>/
```

One tree per active harness (`claude`, `codex`, `gemini`, `opencode`), each
holding the per-harness `<harness>-<skill>/` directories that `build_bundle`
consumes. These roots are the values of
`phase_loop_runtime.build_bundle.DEFAULT_SOURCES`. The tree carries only the
build-relevant inputs — `SKILL.md` plus the aux subdirs `scripts/`,
`assets/` and `references/`; runtime state directories (`handoffs/`,
`reflections/`, `agents/`) are intentionally NOT vendored, because `build_bundle`
never reads them.

The scoped skill set is exactly the phase-loop workflow pack
(`REQUIRED_SKILLS`): `advisor-board`, `execute-detailed`, `execute-phase`,
`plan-phase`, `plan-detailed`, `phase-roadmap-builder`, `phase-loop`, `run-train`,
`skill-editor`, `skill-improvement-planner`, `task-contextualizer`. The old name
`advisor-panel` still resolves to `advisor-board`, and the packaged bundle ships a
compatibility shim under that name.
The `advisor-board` skill is source-first in this repository and stays thin over
`phase_loop_runtime.panel_invoker`; no other repository owns a divergent
implementation of it.

## Auxiliary files

`scripts/` and `assets/` are harness-agnostic: `build_bundle` copies each one
into the shared bundle from the first harness (in `ACTIVE_HARNESSES` order) that
provides it.

`references/` holds the prose a `SKILL.md` links for progressive disclosure
(agent-harness#1358), so placement follows who links each file. A reference file
goes into the shared bundle when another harness's `SKILL.md` links it by its
`references/<path>` and ships no copy of its own. Otherwise it goes into
`_overrides/<harness>/references/` and installs only for that harness. A
harness-only reference is copied verbatim; it is not neutralized and its
`<harness>-` tokens are not expanded. Link reference files one level deep from
`SKILL.md`, and open any reference file over 100 lines with a table of contents.

## The bundle pipeline

```
skills-src/<harness>/            authored canonical source (IF-0-CANON-1)
    │  build_bundle  (neutral base from codex + per-harness _overrides)
    ▼
phase-loop-skills/               committed bundle, parity-gated (IF-0-CANON-2)
    │  scripts/sync_skills_bundle.py
    ▼
src/phase_loop_runtime/skills_bundle/   ships in the wheel
```

## Provenance of the committed bundle

`phase-loop-skills/` is **generated, not hand-edited**. It is produced by
`build_bundle(skills-src/)` via the regenerate command below. The hand-authored
`phase-loop-skills/README.md` is the one exception — it is a bundle index, not
`build_bundle` output, and is excluded from the parity comparison.

## Regenerate (one command)

After editing anything under `skills-src/`:

```sh
python phase-loop-runtime/scripts/regenerate_skills_bundle.py   # skills-src/ -> phase-loop-skills/
python phase-loop-runtime/scripts/sync_skills_bundle.py         # phase-loop-skills/ -> packaged skills_bundle/
```

Both steps are self-contained — no dotfiles checkout required.

## Parity gate (IF-0-CANON-2)

`phase-loop-runtime/tests/test_skills_canon_parity.py` (and the
`.github/workflows/skills-parity.yml` job) fail the build when the committed
`phase-loop-skills/` is not byte-identical to a fresh
`build_bundle(skills-src/)`. The downstream `phase-loop-skills/` ->
`skills_bundle/` half stays guarded by `test_skills_bundle_drift.py`.

## Cutover status

The v50 cutover is complete. The fleet dotfiles no longer carry their own
`*-config` phase-loop skill roots; they install these skills from a pinned
agent-harness clone's `phase-loop-skills/`. `skills-src/` is the only authored
source.

`phase-loop build-bundle` still accepts explicit harness roots. Pass `--source` once
per harness root (claude, codex, gemini, opencode); a single parent directory is
rejected because the harness cannot be inferred from it. Without `--apply` the command
is read-only, and `--destination` defaults to `vendor/phase-loop-skills`, so name
`phase-loop-skills` explicitly when regenerating this repository's bundle. The two
scripts above are the supported regenerate path.
