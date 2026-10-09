# Rule enforcement registry

`phase_loop_runtime/rule_enforcement.json` (schema `rule_enforcement.v1`) lists normative
rules from the skills we ship and says what refuses a violation of each. It ships in the
package because the harness acts on client repos: the rules that govern a run are the ones
in shipped `SKILL.md` text, not this repo's `AGENTS.md`. Tracking: agent-harness#1321
(REPORT 1.13, `spikes/pstack-comparison/REPORT.md`).

## Why

Prefer an enforcer over more text (`docs/agent-phase-convergence.md` §5). The order of
preference is: remove the possibility architecturally, then make the bad state
unrepresentable, then a validator or test, then prose last, and only for judgment calls.
Until now nothing showed which of our prose rules had a mechanism behind them.

## Row semantics

| `status` | Required fields | Meaning |
|---|---|---|
| `enforced` | `enforcers` (≥1), `negative_control` | Named code refuses a violation; the named test shows it refusing |
| `unenforced` + `gap` | `tracking` (`repo#N`) | A mechanism could exist and does not yet |
| `unenforced` + `judgment` | — | Prose is the correct, final level |

Every row quotes its rule. `quote` must appear in every shipped harness copy of the skill;
use `harness_quotes` where a harness words it differently. Enforcers are either
`module` (`phase_loop_runtime.<mod>:<symbol>`) or `skill_script` (a path inside each
shipped copy of the skill).

## What refuses a bad row

`phase-loop-runtime/tests/test_rule_enforcement_registry.py` fails when a quote drifts out
of any harness copy, an enforcer symbol or script disappears, a field contradicts the
status, or a gap has no repo-qualified tracking ref. It also **runs** every negative
control and fails if any does not run and pass. A control that is merely present, or that
skips in CI, proves nothing.

What it does not prove: that the enforcer covers the whole rule. The negative control is
the evidence for the part it covers; read it before trusting a row.

## Adding or changing a row

- Edit skill text in `skills-src/` (canonical), regenerate the bundle, and then update
  the row's quote. The registry test will refuse the stale quote until you do.
- When a gap gets an enforcer, flip the row to `enforced` in the same change.
- When a correction repeats on an `unenforced`/`gap` row, escalate it to a mechanism.
  Adding more prose does not fix it. The aggregator gates planned in
  agent-harness#1321 (REPORT 1.14/1.15) will read this registry to apply that rule.
- Coverage is partial on purpose. The seed lists rules that already had enforcers, plus
  one row of each unenforced kind. The registry does not require every rule to be listed.
