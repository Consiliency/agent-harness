# Plan word budget

`validate_plan_doc.py` check (S) warns when a phase plan's body is longer than its word
budget. The budget applies to the execution plan only. Frozen artifacts the plan references
(contracts, schemas, freeze-gate payloads) have no cap, so the fix for an over-budget plan is
to move detail into one of those and point at it, not to delete it. Rationale:
`docs/agent-phase-convergence.md` §1.

## The budget

`base_words + per_lane_words × lanes`, where `lanes` is the number of `SL-N` stanzas in
`## Lane Index & Dependencies`. Words are counted like `wc -w`, excluding YAML frontmatter.

The built-in default is **2000 + 500 per lane**. Across this repository's 39 phase plans it
flags five: the four 13k–21k-word plans and EXECFIND. A flat cap flagged healthy seven-lane
plans as well.

## Configuration: `.phase-loop-planning.toml`

Optional; without it the default applies. The file sits at the repository root and is
committed like any other source file. It is not under `.phase-loop/`, because the runtime
adds that directory to `.git/info/exclude`, and a config there could not be committed or
reviewed.

```toml
[plan_budget]
base_words = 2000        # non-negative integer
per_lane_words = 500     # non-negative integer
mode = "warn"            # warn (default) | error | off

[plan_budget.phases.EXAMPLE]   # per-phase exception; alias match is case-insensitive
base_words = 8000              # unset keys inherit from [plan_budget]
```

Settings are applied in this order, most specific first:

1. `--word-budget N` on the validator command line: a flat budget with no per-lane term. It
   re-enables a repo-level `mode = "off"`.
2. The `[plan_budget.phases.<ALIAS>]` entry matching the plan's frontmatter `phase:`.
3. `[plan_budget]`.
4. The built-in default.

The budget value is never read from the plan, but two properties of the per-phase match
need review:

- **A plan's `phase:` line selects the exception.** The file name does not bind it, so a
  plan whose frontmatter names another phase gets that phase's exception. Review a plan's
  `phase:` line as you would the exception itself.
- **One alias is shared across roadmaps.** Entries are keyed by alias alone, and aliases
  are not unique across roadmaps (INTEG and RUNTIME appear in both v10 and convergence-v1),
  so one entry applies to every roadmap that reuses the alias.

## Errors

- **Malformed config:** an unknown key or top-level table, a `phases` table anywhere but
  directly under `[plan_budget]`, a mode outside `warn | error | off`, a negative or boolean
  count, or invalid TOML is a validation error, never silently ignored. Every
  `[plan_budget.phases.<ALIAS>]` entry is checked, including ones that match no plan.
- **No TOML parser:** on Python 3.10, which has no `tomllib`, the validator falls back to
  `tomli`. If neither is installed and the config file exists, that is also an error rather
  than a silent fall-back to the defaults.

## Warnings

- **Undeclared alias:** a `[plan_budget.phases.<ALIAS>]` entry whose alias no roadmap in the
  repository declares (any `specs/phase-plans-*.md`, nested paths included, whatever its
  status) applies to no plan.
  The validator reports it as `(S) WARN: [plan_budget.phases.<ALIAS>] …`, so a typo such as
  `CONFROM` surfaces instead of being silently ignored. It is reported in every mode,
  including `off`, and stays a warning under `mode = "error"`: a phase renamed in its
  roadmap would otherwise fail every plan in the repository, and a mistyped exception
  already fails its intended plan through the budget itself. If `phase_loop_runtime` is not importable, the validator prints an `(S) INFO` line
  saying the aliases were not checked.
