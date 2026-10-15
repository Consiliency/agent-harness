# claude-plan-phase — lane validation checklist

Reference for `claude-plan-phase` (linked from its `SKILL.md`). Phase-loop
adapter runs read this file too: it is not preloaded with the skill.

## Lane validation checklist

Before writing the plan doc, verify:

- [ ] **Disjoint file ownership** — no two lanes' `Owned files` globs intersect. For generated files, call out shared-generated status in Execution Notes.
- [ ] **Owned files is inline, one line** — no nested bullets; comma-separated backticked concrete paths/globs only. Do not use prose entries such as "callsite wiring", "new migration file", "or equivalent", or "additions to"; resolve those to actual files before writing the plan.
- [ ] **DAG has no cycles** — a topological sort of `Depends on:` succeeds.
- [ ] **Every `impl` task has a preceding `test` task** in the same lane.
- [ ] **Every acceptance criterion is a testable assertion**, not prose. "Users can log in" is not testable; "`POST /api/auth` returns 200 with a valid session cookie for a registered user" is. `validate_plan_doc.py` WARNs (check K) on a criterion that names no command/path/assertion.
- [ ] **Reference the roadmap goal ID, don't restate it.** When the anchored roadmap phase declares `EC-<ALIAS>-<N>` exit-criterion IDs, author each acceptance item as `- [ ] EC-<ALIAS>-<N> — proven by <command>` — reference the goal by ID (the roadmap exit-criterion is the single source of truth) rather than restating the goal text, so validation always checks the plan against the original goal and a plan can never silently weaken it. Every declared EC-ID should be referenced by ≥1 acceptance item (runtime `goal-coverage` + `validate_plan_doc.py` check P). Write the ID as **plain text at the item's start** — `- [ ] EC-<ALIAS>-<N> — …` — never backticked or bolded (`` `EC-…` ``/`**EC-…**` are not recognized as leading refs), and copy the alias **verbatim** from the roadmap (a case- or digit-drifted `EC-p1-1` reads as a dangling ref). One item may reference several IDs when a single command proves them: `- [ ] EC-<ALIAS>-1, EC-<ALIAS>-2 — proven by \`<cmd>\``. Plan-internal done-conditions (no EC-ref) stay allowed. If the phase declares no EC-IDs (legacy), author testable assertions as before.
- [ ] **Each acceptance criterion names the command that proves it.** The definition of done (canonical term: `acceptance_criteria`) and the `## Verification` commands are one contract, not two parallel lists — cite the proving command (or test file) in or beside each `- [ ]` item so done is mechanically checkable.
- [ ] **Grep assertions are paired with tests.** Any acceptance criterion using `rg` or `grep` as its sole check must also cite a test file — grep alone is defeated by renaming a symbol to pass the regex.
- [ ] **UI changes get a visual check.** When any lane owns UI/visual files (`*.tsx`/`*.jsx`/`*.vue`/`*.svelte`, `*.css`/`*.scss`, `components/**`), `## Verification` must include a browser/screenshot step (Playwright-via-PMCP or claude-in-chrome) and at least one acceptance criterion phrased as a visually observable outcome. `validate_plan_doc.py` WARNs (check L) when UI files change but Verification names no browser step.
- [ ] **Interface freeze gates are concrete** — name the symbol/endpoint/migration, not a vibe.
- [ ] **Stale-base resilience** — for each lane that isn't a DAG root, list every upstream symbol, migration number, or file path it reads under `Interfaces consumed`. This gives `claude-execute-phase` evidence to verify the base wasn't stale and narrows the blast radius of a mis-based commit. Execution Notes must call out "if lane teammate finds its worktree base is pre-<upstream-SL>, stop and report — do not rebase silently."
- [ ] **Synthesis lanes are explicit reducers** — any lane that writes a docs summary, truth table, readiness matrix, release summary, or other synthesized artifact lists every producer lane under `Depends on` and every consumed finding under `Interfaces consumed`. Mark these lanes `Parallel-safe: no`.
- [ ] **No completion-order assumptions** — the plan never relies on lane numbering, prose ordering, or "last lane" wording to sequence final artifact writes; the DAG is the only sequencing mechanism.
- [ ] **Cross-lane file deletions called out** — if any lane legitimately deletes a file that another lane produces (rare but real: a lane replacing a stub), record it under Execution Notes' "Known destructive changes" block.
- [ ] **Expected add/add conflicts declared** — if SL-0 preamble stubs a file that a lane replaces, add it under Execution Notes' "Expected add/add conflicts" block.
- [ ] **SL-0 re-exports use `__getattr__` lazy form** — declared under Execution Notes' "SL-0 re-exports" block.
- [ ] **Plan doc passes `validate_plan_doc.py`** — run the validator and confirm zero errors before calling `ExitPlanMode`. The validator catches structural issues (missing headings, duplicate lane IDs, malformed task tables) that manual review misses.
- [ ] **Terminal `SL-docs` lane present** — every phase plan must include the docs-sweep lane from the docs-sweep template in `references/lane-templates.md`. `Depends on:` lists every other lane in the phase. No opt-out; a phase with no doc changes still runs the lane and records that.
