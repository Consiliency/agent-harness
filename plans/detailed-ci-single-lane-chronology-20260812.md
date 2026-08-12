# Detailed plan: run the heavy chronology proof in two lanes, not four (r2, panel-reconciled)

**r2 (2026-08-12): reconciled against board findings.** codex: Gate A is py3.12-only, and the
node executes version-sensitive subprocess machinery (the py3.10-vs-3.12 egg-info class is a
recorded incident, agent-harness#382) — full deselection loses real interpreter coverage. r2
keeps the node in the OLDEST matrix lane (py3.10) plus Gate A (3.12 clean-room): version spread
preserved at half the r1 target's... at 2 of 4 executions instead of 4. Both seats: Gate A's
45-minute timeout cannot absorb a ~40-minute node plus wheel build and suite — raised to 100.
codex: `-q` prints no per-node ids, so r1's grep verification could not work — replaced with
junitxml evidence.

**Status: DRAFT — do not land before agent-harness#477 merges (frozen count-of-6 depends on main holding still).**

## Task
Stop executing `test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation` in all three pytest matrix lanes. Run it only in Gate A (clean-room, standalone-from-wheel), which remains the authoritative merge gate. Post-#477, the node costs ~40 min per lane per push; 4× duplication is ~2.7 runner-hours of billed Blacksmith time per push for zero added rigor — the node tests git history and archive bytes, not Python-version behavior, and cross-version digest identity was proven explicitly during the #517 work.

## Research summary
`.github/workflows/test.yml` matrix job runs `python -m pytest -m "not dotfiles_integration" --ignore tests/test_legible_roadmap_contract.py --ignore tests/test_legible_evidence.py` from `phase-loop-runtime/` (line ~82). Gate A runs `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, which executes the full suite from an installed wheel in an isolated venv — the strictest environment. The chronology node's cost is marker-gated: cheap pre-#477, ~40 min once the implementation and capability marker are on main.

## Changes

### `.github/workflows/test.yml` (modify)
- matrix `Run standalone test suite` step — add the `--deselect` for the chronology node to the
  py3.11 and py3.12 matrix lanes ONLY (condition on `matrix.python-version`); py3.10 keeps it —
  reason: remove 2 duplicate executions while preserving oldest-interpreter coverage of the
  node's subprocess machinery
- Gate A job — raise `timeout-minutes` from 45 to 100 — reason: post-#477 the node (~40 min)
  plus wheel build and full suite exceeds 45
- Gate A / py3.10 lanes — add `--junitxml` for the suite run — reason: durable per-node evidence
  that the chronology node executed and passed (`-q` prints no node ids)
- comment above the step — state the single-authoritative-lane rule and name Gate A as the owner — reason: prevent a future tidy-up from "fixing" the asymmetry

### `phase-loop-runtime/scripts/gate_a_cleanroom.sh` (verify, no change expected)
- confirm the node is NOT deselected there (it must keep running in Gate A)

## Documentation impact
- `CHANGELOG.md` — add — CI surface change (lane ownership of the chronology proof)

## Dependencies & order
1. agent-harness#477 merged and CONFORM `completed` (hard gate — nothing lands before)
2. This plan (single commit)

## Verification
- Push a trivial branch: py3.11/py3.12 lanes complete in pre-#477 times; py3.10 and Gate A still
  execute the node — proven from the junitxml artifact containing the node id with a pass
- `gh pr checks`: 8 checks green

## Acceptance criteria
- [ ] py3.11/py3.12 lanes no longer collect the chronology node; py3.10 still does
      (`--collect-only` per lane)
- [ ] junitxml from Gate A and py3.10 contains the node id with a pass
- [ ] Gate A `timeout-minutes` = 100
- [ ] No other test selection changed (`--collect-only` diff shows exactly one node delta in
      exactly two lanes)

## Execution policy
- execute: effort=low, reason=two-line workflow change with mechanical verification
