# claude-plan-phase — model and effort tiering

Reference for `claude-plan-phase` (linked from its `SKILL.md`). Phase-loop
adapter runs read this file too: it is not preloaded with the skill.

## Model & Effort Tiering (right-size per lane, don't default to the ceiling)

The runtime resolves one planning model per executor (`codex` → `gpt-6-astra`,
`claude` → `claude-opus-5`), so **reasoning effort is the primary cost dial.**
The normalized effort ladder, cheapest first, is:

`minimal` < `low` < `medium` < `high` < `xhigh` < `max`

Registry action defaults today are blunt — for this executor `plan`/`roadmap`/`review`
resolve to `max` and `execute`/`repair` to `high` (`EXECUTOR_EFFORT_OVERRIDES` in
`profiles.py` is the source; read it rather than trusting this sentence) — applied
uniformly regardless of how hard the lane actually is. As the planner you have the complexity signal the runtime
lacks; use it:

- **Default each lane to the cheapest effort you believe will succeed**, not the
  action default. A mechanical edit, a config bump, a docs-sweep lane, or a
  rename rarely needs more than `low`/`minimal`.
- **Escalate only with a stated reason.** Subtle concurrency, cross-module
  refactors, security-sensitive logic, or ambiguous specs justify `high`/`xhigh`;
  record *why* in the rule's `reason=`.
- Express the choice in an `## Execution Policy` section the runtime parses
  (selector = `default`, an action, or a lane alias):

```
## Execution Policy
- default: effort=low, reason=most lanes are mechanical this phase
- execute: effort=medium
- SL-3: effort=high, reason=constant-time comparison is subtly wrong-prone
- SL-7: effort=minimal, reason=docs sweep only
```

Two hard syntax rules the parser enforces (a malformed line fails the whole
section, not just that line):

- **Lane selectors are the numeric lane id** (`SL-3`, `P2A` → use `lane <name>:`
  for non-numeric names). `SL-DOCS`-style names are rejected; write `SL-7` or
  `lane SL-DOCS: …`.
- **No commas inside a `reason=` value** — the comma separates assignments, so
  `reason=docs sweep, no logic` breaks parsing. Keep reasons comma-free.

Operator `--model`/`--effort` and CLI overrides still win, so this never blocks
a human from forcing a tier. The goal is to stop paying `high` for a one-line
change by default.

**Model class (vendor-agnostic role).** Alongside effort, a rule may set a
`model_class` — `planner` / `implementer` / `worker` — which resolves to a
concrete model per executor. The shipped `model_policy` already routes planning
to the planner class at `max` and implementation to the implementer class, so
you rarely set this by hand; reach for it when a specific lane wants a cheaper
worker-class model for a bounded, schema-checked subtask. The `worker` class
must never author a final patch, and an executor that can't run at `max` (e.g.
gemini) is never the max-effort planner of record.

**Run mode is separate.** `model_policy` (what model) is independent of
`run_mode` (autonomous default vs opt-in governed review). Planning a phase does
not enable the governed panel; that is an operator opt-in.
