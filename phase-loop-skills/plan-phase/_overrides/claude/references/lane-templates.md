# claude-plan-phase — lane templates

Reference for `claude-plan-phase` (linked from its `SKILL.md`). Phase-loop
adapter runs read this file too: it is not preloaded with the skill.

## Contents

- Preamble lane archetype (SL-0)
- Docs-sweep lane template (SL-docs)

## Preamble lane archetype

The "preamble lane" concentrates single-writer files AND freezes interface shapes on Day 1, letting all downstream lanes run in parallel without contending for the same index/config/init file.

**When to use**: ≥2 parallel lanes would otherwise need to touch the same index/config/init file, OR ≥2 lanes consume the same frozen type.

Template sketch:

```markdown
### SL-0 — Preamble (interface + single-writer setup)
- **Scope**: Freeze shared types and stub the single-writer files every downstream lane will import from.
- **Owned files**: `src/index.ts`, `src/config.ts`, `src/__init__.py` (list every shared index/config/init file)
- **Interfaces provided**: `FooContract`, `BarRegistry`, `WorkerRouter` (frozen type names)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal in preamble position — no downstream lane modifies SL-0's files)
- **Tasks**: one test task pinning the frozen type shapes; one impl task adding the stubs; one verify task
```

Downstream lanes depend on `SL-0` and consume its frozen interfaces; they must not list any SL-0 owned file in their own `Owned files`.

## Docs-sweep lane template

Every phase plan must include this as the final lane. Copy verbatim into the `## Lanes` section, adjust `Depends on:` to list every other `SL-N` in the phase, and edit the `Scope notes` if the phase has atypical docs impact.

```markdown
### SL-docs — Documentation & spec reconciliation

- **Scope**: Refresh the docs catalog, update cross-cutting documentation touched or invalidated by this phase's impl lanes, and append any post-execution amendments to phase specs whose interface freezes turned out wrong.
- **Owned files** (read `.claude/docs-catalog.json` for the authoritative list; a minimum set is below, but the catalog is canonical):
  - Root: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `MIGRATION.md`, `ARCHITECTURE.md`, `DESIGN.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`
  - Agent indexes: `llm.txt`, `llms.txt`, `llms-full.txt`
  - Service manifests: `services.json`, `openapi.yaml`/`.yml`/`.json`
  - `docs/**`, `rfcs/**`, `adrs/**`
  - `.claude/docs-catalog.json` (this lane maintains it)
  - The current phase's section of `specs/phase-plans-v<N>.md` (append-only amendments)
  - Any prior `plans/phase-plan-v<N>-<alias>.md` or prior spec phase sections whose contracts this phase invalidated (prior-phase amendments allowed)
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal)
- **Depends on**: every other `SL-N` in this phase

**Tasks**:

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan: `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`. Picks up any new doc files created by impl lanes; preserves `touched_by_phases` history. |
| SL-docs.2 | docs | SL-docs.1 | per catalog | For each file in the catalog, decide: does this phase's work change it? If yes, update the file and append the current phase alias to its `touched_by_phases`. If no, leave it. Record in commit message any files intentionally skipped. |
| SL-docs.3 | docs | SL-docs.2 | `specs/phase-plans-v<N>.md`, prior plans | Append `### Post-execution amendments` subsections to any phase section (current or prior) whose interface freeze was empirically wrong this run. Named freeze IDs + dated correction. |
| SL-docs.4 | verify | SL-docs.3 | — | Run any repo doc linters (`markdownlint`, `vale`, `prettier --check`, Mermaid/PlantUML render check). If none configured, no-op. |
```

No opt-out. A phase with nothing to change still runs `SL-docs` and records that explicitly in its commit message — the audit trail.
