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

Every phase plan includes a terminal docs reducer. Use a free numeric ID
(`SL-9` below is an example), list it in the lane index, and set its dependencies
to every producer lane. Replace every placeholder with the exact paths and
interfaces needed by this phase. Owned paths must be a single inline bullet and
must not overlap an implementation lane; move shared docs ownership here before
execution. A docs catalog is optional repo infrastructure, not a shipped helper.

```markdown
### SL-9 — Documentation & spec reconciliation
- **Scope**: Update the documentation affected by this phase, or record why no change is needed.
- **Owned files**: `<exact-doc-path>`, `<other-disjoint-doc-path>`
- **Interfaces provided**: (none)
- **Interfaces consumed**: `<producer-interface>`
- **Parallel-safe**: no

- verify: `<configured-doc-check>`

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-9.1 | docs | — | `<exact-doc-path>` | — | `<configured-doc-check>` |
| SL-9.2 | verify | SL-9.1 | `<exact-doc-path>` | — | `<configured-doc-check>` |
```

Use repo-configured doc checks. Do not invoke an absent
`_shared/scaffold_docs_catalog.py`. Record any necessary roadmap amendment by
its affected gate/goal ID, preserving already executing phase scope.

No opt-out. A phase with nothing to change still runs the docs reducer and records that explicitly in its commit message — the audit trail.
