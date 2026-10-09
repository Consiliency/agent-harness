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
| `enforced` | `enforcers` (≥1), `negative_control` | Named code refuses a violation; the named test shows it refusing, not warning |
| `unenforced` + `gap` | `tracking` (`repo#N`) | A mechanism could exist and does not yet |
| `unenforced` + `judgment` | — | Prose is the correct, final level |

Every row quotes its rule. `quote` must appear in every shipped harness copy of the skill;
use `harness_quotes` where a harness words it differently. Enforcers are either
`module` (`phase_loop_runtime.<mod>:<symbol>`) or `skill_script` (a path inside each
shipped copy of the skill).

A `negative_control` is an exact pytest node id under `phase-loop-runtime/`
(`tests/<file>.py::<Class>::<test>` or `tests/<file>.py::<test>`). It must call every
enforcer its row lists in the pytest process itself, not in a subprocess, and must reach a
`skill_script` enforcer through that script's `main()`. Its assertion must be on what
`main()` refuses: for the plan validator, that the violation adds one finding to
`main()`'s own error count. A finding the validator only warns about is not a refusal.

## What refuses a bad row

`phase-loop-runtime/tests/test_rule_enforcement_registry.py` fails when a quote drifts out
of any harness copy, an enforcer symbol or script disappears, a field contradicts the
status, or a gap has no repo-qualified tracking ref. It also **runs** every negative
control in a child pytest. A control counts as run only if its exact node id has a
passed call-phase report and no report of any phase (setup, call, teardown or a subtest)
that skipped or failed. A control that is merely present, deselected, set up without its
body running, or skipped in CI proves nothing.

The child reads no pytest configuration from outside the gate. It drops every `PYTEST_*`
variable, disables entry-point plugin autoload, reads only an empty ini file the gate
writes, and loads no `conftest.py` above `phase-loop-runtime/`. The only plugins it
loads are pytest's own, the gate's report probe, and this repo's `conftest.py` files.
In-tree code is trusted: a hook in `tests/conftest.py` can still stand in for a body
(CONFORM-migrated ids do this in canonical mode), so a control must not be such an id.
The gate does not defend against code written to forge pytest results, nor against
Python's own startup hooks (`sitecustomize`, `.pth` files on `PYTHONPATH`), which belong
to the interpreter environment rather than to pytest's configuration.

For each enforcer of each `enforced` row, the test then runs the row's control with
that one enforcer replaced by a stub that refuses nothing. It fails unless the stub is
reached and the control fails its own assertion. A `skill_script` stub must also be
reached with the script's `main()` on the stack. Each `skill_script` check is also run
demoted: its findings are kept but marked `WARN: `, so `main()` warns instead of
refusing. The control must fail its own assertion then too.

What it does not prove: that the enforcer covers the whole rule. The negative control is
the evidence for the part it covers; read it before trusting a row.

## Adding or changing a row

- Edit skill text in `skills-src/` (canonical), regenerate the bundle, and then update
  the row's quote. The registry test will refuse the stale quote until you do.
- When a gap gets an enforcer, flip the row to `enforced` in the same change.
- A new or repointed `negative_control` must be an exact node id and call every enforcer
  the row lists in-process, a `skill_script` one through the script's `main()`. It must
  assert on `main()`'s refusal, not only reach the check. The enforcer-kill and
  demotion tests refuse a control that still passes without a check, or with it warning.
- When a correction repeats on an `unenforced`/`gap` row, escalate it to a mechanism.
  Adding more prose does not fix it. The aggregator gates planned in
  agent-harness#1321 (REPORT 1.14/1.15) will read this registry to apply that rule.
- Coverage is partial on purpose. The seed lists rules that already had enforcers, plus
  one row of each unenforced kind. The registry does not require every rule to be listed.
