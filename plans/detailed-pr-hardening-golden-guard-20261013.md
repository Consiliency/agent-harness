# Detailed plan: align the historical launch-golden guard

## Task

Repair the sole full-suite failure on agent-harness#1581 before the owner-authorized
merge. Keep all runtime code, launch metadata and audit policy unchanged.

## Research summary

The full Python 3.10 CI suite reported one failure and 13,315 passing tests.
`test_golden_delta_is_only_final_schema_exclusion` reverses previously approved
instruction deltas before comparing a historical canonical digest. The new PR
instructions alter two prompt strings, so the existing reverse transformations
no longer match. The ordinary launch-golden and parity tests already pass.

## Changes

- Add `phase-loop-runtime/tests/data/launchspec_golden/pre_1581_pr_hardening.json`:
  a frozen historical input mapping the two changed prompt strings at existing
  commit `483e354f76c5723a291ac920ea189d47e64e142b` back to input `19022000`.
  Generation must assert that these are the only changed golden fields.
- Modify `phase-loop-runtime/tests/test_executor_exited_without_closeout_785.py`:
  require each current prompt to equal that frozen input and restore its prior
  bytes before the older normalization steps. Preserve the final historical digest
  assertion and every schema, tool-policy, argv and lifecycle assertion.
- Register and complete this plan through typed `plans/manifest.json` helpers.
  Ignored handoff, verification and reflection output is allowed. Preserve all
  earlier companion-plan changes and the primary checkout's unrelated gateway log.

## Documentation impact

No public behavior changes. The test's qualified PR reference and frozen input
document the intentional instruction delta; no product documentation update.

## Dependencies & order

Record the reproduced failure, register the plan, create the frozen input, and
repair the guard. Verify and publish through the supported human adapter. Obtain
Sol's delta review against the new committed head; carry Astra's prior AGREE
because this adds no runtime behavior. Merge only after required CI passes.
The owner already authorized merge; no admin bypass or force push is permitted.

## Verification

With the existing interpreter and `PYTHONPATH=src:tests` in `phase-loop-runtime/`:

1. Reproduce `python -m pytest -q tests/test_executor_exited_without_closeout_785.py::test_golden_delta_is_only_final_schema_exclusion` before editing.
2. Run `python -m pytest -q tests/test_executor_exited_without_closeout_785.py tests/test_launchspec_golden.py tests/test_publication_mode_1392.py tests/test_skills_canon_parity.py tests/test_publishing.py` after editing.
3. Run pinned `uvx ruff@0.15.5 check .`, `git diff --check`, and validate the final verification artifact.
4. Review the final test/fixture delta and require the existing full CI suite before merge.

## Acceptance criteria

- [x] Frozen input proves only the two intended prompt strings changed between the declared input revisions.
- [x] The legacy guard passes while retaining its historical digest and all earlier invariant checks.
- [x] Selected regression tests and pinned lint pass; the delta contains no runtime code or policy changes.
