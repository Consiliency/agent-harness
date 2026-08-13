# Detailed plan: run the heavy chronology proof in two lanes, not four (r3, board-reconciled)

**Status: held — do not land before agent-harness#477 merges.**
**r3 (2026-08-12): reconciles round-2 board findings (4 seats, all DISAGREE). r2's `## Task` still
carried r1 text (all four seats); the matrix-lane timeout arithmetic was applied only to Gate A
(grok B1 / Fable B1); the Gate A junitxml path was unimplementable inside the declared change set
(grok B2 / codex / Fable B2 — `pytest.main` hardcodes `-q` under `env -i`, and the `$WORK` EXIT
trap destroys anything written inside it). All fixed below; `gate_a_cleanroom.sh` is now
declared MODIFIED.**

## Task
Run `test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation`
in exactly TWO of the four CI executions: the **py3.10 matrix lane** (oldest supported
interpreter — the node executes version-sensitive subprocess machinery; the py3.10-vs-3.12
egg-info divergence is a recorded incident class, agent-harness#382) and **Gate A** (py3.12
clean-room; its sparse source staging preserves 3.12 source-build coverage). Deselect it from the
py3.11 and py3.12 matrix lanes only. Post-#477 the node costs ~40 min per execution; 4→2
executions saves ~80 billed minutes per push while keeping both interpreter endpoints.

## Changes
### `.github/workflows/test.yml` (modify)
- matrix `Run standalone test suite` step — add the node `--deselect`, conditioned on
  `matrix.python-version` ∈ {3.11, 3.12}; py3.10 keeps the node
- matrix pytest job `timeout-minutes: 45` → `100` (the retained node makes py3.10 exceed 45 by
  the same arithmetic that forced Gate A's raise; timeout is job-level and the cheap lanes are
  unaffected at ~5 min)
- cleanroom (Gate A) job `timeout-minutes: 45` → `100`
- py3.10 lane — add `--junitxml="$RUNNER_TEMP/junit-py310.xml"` to the suite invocation
- add `actions/upload-artifact` steps for both junitxml files (py3.10 lane; Gate A's exported
  file, below) — durable per-node evidence; without upload the xml dies with the runner
- add a guard comment AND a collection assertion: a step fails if NO lane collects the node
  (protects against the documented matrix-conditional-vanishing hazard at test.yml:30-32 — if
  py3.10 is ever dropped from the matrix, the retention must fail loudly, not narrow silently)
### `phase-loop-runtime/scripts/gate_a_cleanroom.sh` (modify — reclassified from "no change")
- add `--junitxml` to the `pytest.main([...])` argument list (the `-q` heredoc invocation)
- write the xml to a path OUTSIDE `$WORK` (or copy out before the `trap rm -rf $WORK EXIT`
  fires), exported for the workflow's upload step

## Documentation impact
- `CHANGELOG.md` — add — CI lane ownership + Gate A evidence surface change

## Dependencies & order
1. agent-harness#477 merged and CONFORM `completed` (hard gate)
2. This plan (single commit)

## Verification
- Push a trivial branch: py3.11/py3.12 lanes at pre-#477 duration; py3.10 and Gate A execute the
  node — proven from the two uploaded junitxml artifacts containing the node id with a pass
- `--collect-only` per matrix lane: node present in py3.10 only; collection-guard step green
- `gh pr checks`: all checks green

## Acceptance criteria
- [ ] py3.11/py3.12 lanes no longer collect the chronology node; py3.10 still does
- [ ] Both junitxml artifacts (py3.10 lane, Gate A) uploaded and contain the node id with a pass
- [ ] `timeout-minutes` = 100 on BOTH the matrix pytest job and Gate A
- [ ] Collection-guard fails when no lane retains the node — proven once by a deliberate
      LANE-REMOVAL mutation (drop py3.10 from the matrix) on a scratch branch; a deselect-only
      mutation is insufficient, since an in-matrix guard vanishes with the lane (the
      test.yml:30-32 hazard the guard exists for)
- [ ] No other test selection changed (`--collect-only` diff shows exactly one node delta in
      exactly two lanes)

## Execution policy
- execute: effort=low, reason=workflow + one bounded script change, mechanically verifiable
