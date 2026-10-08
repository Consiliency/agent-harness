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

## Configuration: `.phase-loop/planning.toml`

Optional; without it the default applies.

```toml
[plan_budget]
base_words = 2000        # non-negative integer
per_lane_words = 500     # non-negative integer
mode = "warn"            # warn (default) | error | off

[plan_budget.phases.CONFORM]   # per-phase exception; alias match is case-insensitive
base_words = 8000              # unset keys inherit from [plan_budget]
```

Settings are applied in this order, most specific first:

1. `--word-budget N` on the validator command line: a flat budget with no per-lane term. It
   re-enables a repo-level `mode = "off"`.
2. The `[plan_budget.phases.<ALIAS>]` entry matching the plan's frontmatter `phase:`.
3. `[plan_budget]`.
4. The built-in default.

The budget is never read from the plan's own frontmatter, so a plan cannot grant itself an
exception. A per-phase exception belongs in the repo config, where review sees it.

## Errors

- **Malformed config:** an unknown key, a mode outside `warn | error | off`, a negative or
  boolean count, or invalid TOML is a validation error, never silently ignored.
- **No TOML parser:** on Python 3.10, which has no `tomllib`, the validator falls back to
  `tomli`. If neither is installed and the config file exists, that is also an error rather
  than a silent fall-back to the defaults.
