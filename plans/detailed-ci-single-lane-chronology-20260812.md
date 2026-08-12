# Detailed plan: run the heavy chronology proof in one authoritative CI lane

**Status: DRAFT — do not land before agent-harness#477 merges (frozen count-of-6 depends on main holding still).**

## Task
Stop executing `test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation` in all three pytest matrix lanes. Run it only in Gate A (clean-room, standalone-from-wheel), which remains the authoritative merge gate. Post-#477, the node costs ~40 min per lane per push; 4× duplication is ~2.7 runner-hours of billed Blacksmith time per push for zero added rigor — the node tests git history and archive bytes, not Python-version behavior, and cross-version digest identity was proven explicitly during the #517 work.

## Research summary
`.github/workflows/test.yml` matrix job runs `python -m pytest -m "not dotfiles_integration" --ignore tests/test_legible_roadmap_contract.py --ignore tests/test_legible_evidence.py` from `phase-loop-runtime/` (line ~82). Gate A runs `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, which executes the full suite from an installed wheel in an isolated venv — the strictest environment. The chronology node's cost is marker-gated: cheap pre-#477, ~40 min once the implementation and capability marker are on main.

## Changes

### `.github/workflows/test.yml` (modify)
- matrix `Run standalone test suite` step — add `--deselect tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation` to the first pytest invocation — reason: remove 3 of 4 duplicate executions; Gate A retains the authoritative run
- comment above the step — state the single-authoritative-lane rule and name Gate A as the owner — reason: prevent a future tidy-up from "fixing" the asymmetry

### `phase-loop-runtime/scripts/gate_a_cleanroom.sh` (verify, no change expected)
- confirm the node is NOT deselected there (it must keep running in Gate A)

## Documentation impact
- `CHANGELOG.md` — add — CI surface change (lane ownership of the chronology proof)

## Dependencies & order
1. agent-harness#477 merged and CONFORM `completed` (hard gate — nothing lands before)
2. This plan (single commit)

## Verification
- Push a trivial branch: matrix lanes complete in pre-#477 times (~4 min); Gate A still executes the node (grep its log for the node id)
- `gh pr checks`: 8 checks, Gate A green including the node

## Acceptance criteria
- [ ] Matrix lanes no longer collect the chronology node (`--collect-only` shows it deselected)
- [ ] Gate A's log contains the node id and passes
- [ ] No other test selection changed (`--collect-only` diff vs pre-change shows exactly one node delta per matrix lane)

## Execution policy
- execute: effort=low, reason=two-line workflow change with mechanical verification
