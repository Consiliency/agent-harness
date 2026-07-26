# Detailed plan: apply and persist repair model-class escalation

## Task

Make the existing governed repair decision real for Consiliency/agent-harness#310:
after the repeated-verification-failure threshold, a regular-tier implementer
repair must launch on the heavy-tier planner model, with durable requested/effective
provenance. Normal execution and first repairs remain on the regular tier.

This plan depends on `detailed-310-role-routing-defaults-20260726.md`, which makes
`planner -> heavy` and `implementer -> regular`. It does not change executor
fallback selection, the escalation threshold, or advisor-panel invocation.

## Current-state findings

- `governed_premerge.next_escalation()` already returns a typed
  `EscalationDecision`: at threshold, `implementer -> planner` with action
  `escalate_class`.
- `runner.py` calls that function after two repeated repair fingerprints but
  writes `model_class_escalation.applied: False`; it then recomputes the normal
  action profile/policy and launches the implementer model again.
- Operator `--model` and `--effort` overrides currently win inside
  `resolve_execution_policy`; escalation must not silently override an explicit
  operator model.
- A subsequent invocation must be able to tell that the preceding repair ran as
  planner class; otherwise every retry starts from implementer and terminal
  escalation can never be reasoned about truthfully.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/profiles.py` (modify)

- Add a focused helper, `apply_model_class_escalation(...)`, that accepts a
  `ResolvedExecutionPolicy`, executor, typed escalation decision/target class,
  and explicit-operator-model presence.
- For `action == "escalate_class"` and no operator model, resolve the target
  through `resolve_model_class(executor, model_class)` and return a replaced
  policy with:
  - the escalated concrete model;
  - the escalated `model_class`;
  - `model_source="runtime model-class escalation"`;
  - an override reason carrying the typed decision reason;
  - the existing effort, executor, fallback, and work-unit fields unchanged.
- Fail closed if the selected executor has no mapping for the target class. Do
  not fall back to its default model and do not infer a model from a name.
- If an explicit operator model is present, return the policy unchanged and a
  typed non-applied reason so metadata cannot claim the operator was overridden.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)

- Keep `next_escalation()` as the only threshold/ladder decision source.
- Retain the decision through dispatch resolution, then call
  `apply_model_class_escalation(...)` after the normal layered execution policy
  resolves and before `resolve_model_selection_from_policy(...)` constructs the
  launch selection.
- Move the model-class decision outside the `if pivot_executor` branch. When no
  fallback executor is configured, continue on the current selected executor and
  still apply the class escalation; absence of an executor pivot must not return
  `repeated_verification_failure` before the heavy-model policy is resolved.
- Only block for “no fallback executor” when a dispatch pivot is independently
  required and model-class escalation cannot provide the next repair attempt.
- Change `repair_loop_pivot.model_class_escalation` to record:
  `applied`, `action`, `from_model_class`, `model_class`, `from_model`,
  `effective_model`, `reason`, and a typed `not_applied_reason` when applicable.
- Persist the effective class/model on the normal launch event metadata. On the
  next repair invocation, read the latest matching event that proves a child was
  actually launched with `model_class_escalation.applied:true`, regardless of
  whether that repair later completed or ended `blocked`. Ignore pre-launch
  blocks, malformed records, stale phase/fingerprint, different executor, and
  `applied:false`; never require verification success, because the failed Opus
  attempt is what advances the ladder.
- Bind recovery to the current `roadmap_sha256` and `phase_sha256` from
  `event_provenance`. An alias/fingerprint match from an older roadmap or phase
  revision is stale and cannot advance the active ladder.
- Keep the executor pivot and model-class escalation as separate recorded axes:
  executor fallback chooses a runnable harness; model-class escalation chooses
  that harness's heavy model.
- Do not implement the planner-terminal `invoke_panel` branch here. When the
  starting class is already planner, preserve `next_escalation()`'s typed action
  in metadata and use the existing repairable terminal/blocking path rather than
  falsely reporting another model switch. A later governed-panel plan may consume
  that action.

### `phase-loop-runtime/tests/test_governed_premerge.py` (modify)

- Keep the pure ladder tests and add/retain assertions for threshold semantics:
  implementer -> planner, planner -> invoke_panel in governed mode, and planner ->
  non-human terminal blocker in autonomous mode.
- Assert no vocabulary or threshold changes are introduced by the application layer.

### `phase-loop-runtime/tests/test_model_class_policy.py` (modify)

- Unit-test `apply_model_class_escalation` for Claude, Codex, and one manual-map
  provider.
- Cover explicit operator model precedence, unmapped-class fail-closed behavior,
  and preservation of effective effort/fallback fields.

### `phase-loop-runtime/tests/test_phase_loop_runner.py` (modify)

- Add an end-to-end mocked repair launch proving two matching failures cause the
  next Claude launch to use `claude-opus-5`, not `claude-sonnet-5`.
- Assert the emitted event says `applied:true`, class `planner`, and carries the
  effective model/source.
- Add negative cases for below-threshold, different fingerprint, different
  executor, roadmap digest, phase digest, malformed/stale metadata, and explicit
  `--model`.
- Add the load-bearing no-fallback case: with only the current Claude executor
  available, two matching Sonnet failures still launch the next repair on Opus.
- Add a continuation case proving an applied planner-class event is recognized on
  the next repair instead of resetting the ladder to implementer.

### `docs/research/model-routing-v2-integration.md` and `CHANGELOG.md` (modify)

- Replace the documented `applied:false` remaining thread with the applied
  regular-to-heavy contract and its operator-override exception.
- State explicitly that this plan does not yet consume the terminal
  `invoke_panel` action.

## Dependencies and order

1. Land `detailed-310-role-routing-defaults-20260726.md`.
2. Add and unit-test the pure policy-application helper.
3. Thread the typed decision through the runner and persist effective metadata.
4. Add history recovery and end-to-end runner coverage.
5. Update documentation.

## Execution Policy

- execute: effort=high, reason=governed retry state and launch-selection semantics
- review: model_class=reviewer, effort=max

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest \
  tests/test_governed_premerge.py \
  tests/test_model_class_policy.py \
  tests/test_phase_loop_runner.py -q -k "escalat or repair_loop or repeated_verification"
PYTHONPATH=src:tests python -m pytest tests/test_phase_loop_runner.py tests/test_governed_premerge.py -q
```

`automation.suite_command`: `cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest tests/test_governed_premerge.py tests/test_model_class_policy.py tests/test_phase_loop_runner.py -q`

## Acceptance criteria

- [ ] A governed repair below the threshold launches the regular implementer model.
- [ ] Repeated matching verification failure records and applies `implementer -> planner`.
- [ ] Model-class escalation proceeds on the current executor when no fallback executor is configured.
- [ ] The resulting Claude repair launch uses `claude-opus-5`; the equivalent provider-specific heavy model is used on other supported executors.
- [ ] Event metadata distinguishes requested class, effective class/model, source, and whether application occurred.
- [ ] An explicit operator model is never silently overridden and is recorded as the non-applied reason.
- [ ] Unmapped target classes fail closed rather than falling back silently.
- [ ] A later retry recognizes the last actually-launched applied planner class for the same phase/executor/fingerprint even when that repair ended blocked.
- [ ] Escalation history is reused only when current roadmap and phase digests also match.
- [ ] Planner-terminal escalation is recorded honestly and is not misreported as an applied second switch.
