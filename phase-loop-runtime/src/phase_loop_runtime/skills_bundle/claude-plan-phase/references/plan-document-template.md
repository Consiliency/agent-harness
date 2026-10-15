# claude-plan-phase — plan document template

Reference for `claude-plan-phase` (linked from its `SKILL.md`). Phase-loop
adapter runs read this file too: it is not preloaded with the skill.

## Contents

- Plan document template
- ID conventions
- Task types & dependency rules

## Plan document template

Use this frontmatter and these headings verbatim — the phase-loop runner trusts
the frontmatter before it trusts the plan body:

```markdown
---
phase_loop_plan_version: 1
phase: <PHASE_ALIAS>
roadmap: <repo-relative roadmap path, e.g. specs/phase-plans-v1.md>
roadmap_sha256: <sha256 of that roadmap file>
---

# <PHASE_ID>: <Phase Name>

## Context
<Synthesized from Explore teammates. What exists, what constrains the design, what will change.>

## Interface Freeze Gates
- [ ] IF-0-<PHASE>-<N> — <one-line description of the frozen interface>
- [ ] IF-0-<PHASE>-<N+1> — …

## Cross-Repo Gates
<Omit entirely if the phase only touches this repo.>
- [ ] IF-XR-<N> — <interface that must be frozen across repo boundaries>

## Lane Index & Dependencies

SL-1 — <lane name>
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-2 — <lane name>
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes

## Lanes

### SL-1 — <lane name>
- **Scope**: <one sentence>
- **Owned files**: `path/one/**`, `path/two/*.ts` (MUST be a single-line inline bullet, comma-separated backticked globs; do NOT use nested sub-bullets — the downstream file-touch auditor expects inline form)
- **Interfaces provided**: `FooContract`, `POST /api/bar`
- **Interfaces consumed**: (none)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `path/one/__tests__/foo.test.ts` | `FooContract` shape | `pnpm test path/one/__tests__/foo.test.ts` |
| SL-1.2 | impl | SL-1.1 | `path/one/foo.ts` | — | — |
| SL-1.3 | verify | SL-1.2 | `path/one/**` | all SL-1 tests | `pnpm test path/one` |

### SL-2 — <lane name>
…

### SL-docs — Documentation & spec reconciliation

(See the docs-sweep lane template in `references/lane-templates.md` for the full lane spec. Copy it verbatim and set `Depends on:` to list every other SL-N in this phase.)

## Execution Notes
- <Parallelism caveats, sequencing gotchas, lanes that can't be worktree-isolated (shared migrations, shared generated files), etc.>
- **Single-writer files**: <files multiple lanes might want to touch but only one is allowed to modify — e.g., barrel index files, generated types, nav config, worker router. List the owner lane for each. If a single-writer file is also touched by a later phase, name this phase's owner lane and have them author-at-plan-time any additions the later phase's consumer lanes will need. Re-opening the file from the later phase's lane adds a cross-phase serialization edge that shouldn't exist.>
- **Known destructive changes**: <any deletions a lane legitimately performs, named by file path. If empty, write "none — every lane is purely additive." This is the whitelist claude-execute-phase's pre-merge check uses to distinguish legitimate deletions from stale-base accidents.>
- **Expected add/add conflicts**: <if SL-0 preamble stubs a file that a later lane replaces the body of, list the file path here. The orchestrator pre-authorizes `git checkout --theirs <path>` resolution at merge time.>
- **SL-0 re-exports**: <if the preamble adds symbols to an `__init__.py`, specify the `__getattr__` lazy pattern (not top-level imports). Eager re-exports break package load when a later lane drops or renames the symbol.>
- **Worktree naming**: claude-execute-phase allocates unique worktree names via `scripts/allocate_worktree_name.sh`. Plan doc does not need to spell out lane worktree paths.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- (If `--consensus` was used) **Architectural choices**: <consensus summary, or unresolved disagreement with dissent recorded>

## Acceptance Criteria
- [ ] EC-<ALIAS>-<N> — proven by `<command / test>`, falsified by `<assertion / negative control>` (must target a production construction site with path-entered control)
- [ ] EC-<ALIAS>-<M> — proven by `<command / test>`, falsified by `<assertion / negative control>` (must target a production construction site with path-entered control)

## Verification
<Concrete end-to-end commands to run after all lanes merge. pnpm, supabase, curl, playwright, etc.>
```

## ID conventions

| ID | Format | Example |
|---|---|---|
| `PHASE_ID` | Spec identifier, else `PHASE-<kebab>` | `PHASE-1-shared-semantics` |
| Lane ID | `SL-<N>` | `SL-3` |
| Task ID | `<LANE_ID>.<N>` | `SL-3.2` |
| Interface freeze | `IF-0-<PHASE>-<N>` | `IF-0-P1-1` |
| Cross-repo freeze | `IF-XR-<N>` | `IF-XR-2` |

Defaults only — if the spec already uses its own identifiers (e.g., `P1-SL-AUTH-01`), adopt those verbatim.

Any non-numeric lane alias (e.g., `SL-docs`) must still appear in the machine-readable `## Lane Index & Dependencies` block as `SL-<N>` for compatibility with downstream audit/validator tooling that expects `SL-\d+`. Its `Depends on:` line must be on its own line (not inlined with prose that could regex-match as a dependency). The alias (e.g., `SL-docs`) remains valid as the author-facing lane heading in `## Lanes`.

## Task types & dependency rules

| Type | Purpose | Rules |
|---|---|---|
| `test` | Write failing tests that pin down the lane's contracts. | Must precede any `impl` task in the same lane. |
| `impl` | Write the code that makes the preceding tests pass. | Must depend on exactly one `test` task in the same lane. |
| `verify` | Run the full lane test suite + any integration checks. | Last task in the lane. Depends on the last `impl` task. |
| `docs` | Update cross-cutting documentation and the docs catalog. | Lives in the terminal `SL-docs` lane. Depends on every other lane's final `verify` task. |
