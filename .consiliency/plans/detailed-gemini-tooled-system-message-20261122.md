# Detailed plan: tooled Gemini seats accept bare agy `system_message` steps

## Task
**Outcome served:** standalone. A jailed Gemini seat's tooled stream that holds agy's own bare
`system_message` steps ends OK. Before this change it was refused with
`gemini_seat_subagent_or_unknown_event`.

On a dev0 board run (0.7.39, agy 1.5.14), the tooled leg was refused with `reason=bad_step_type`
and `step_type=system_message` (`state=DONE`). Three such steps carried only `conversation_id`,
`step_index`, `state`, `step_type` and `duration_seconds`, and all 160 tool steps passed. The
triage is at `~/workspace/reviews/agent-harness-exec/gemini-subagent-triage.md`.

## Research summary
- `panel_invoker._broker_gemini_stream_result(..., tooled=True)` refuses any step whose
  `step_type` is outside `_JAILED_GEMINI_STEP_TYPES`, or that carries `subagent_info`, or whose
  tool name `_jailed_gemini_tool_refusal` refuses.
- `_stream_rejection_walk` (agent-harness#1823) mirrors the parser's rule order. It must admit
  the same steps, so parser and record stay at parity.
- If `_JAILED_GEMINI_STEP_TYPES` were simply widened, a `system_message` with a valid
  `tool_name` or `tool_info`, or with unlisted keys, would pass.
- The parser is in the agy validator closure. Its rule is in `tests/test_agy_qci.py` L41-L50:
  "An edit that keeps every verdict updates this pin in a reviewed change; one that changes a
  verdict bumps the literal." agent-harness#2045 (c99378944) followed it: it moved the closure
  pin only.

## Changes
### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- Add `_JAILED_GEMINI_SYSTEM_STEP_KEYS`, a frozenset of the five observed keys.
- Add `_jailed_gemini_inert_system_step(step)`. It returns true only when `step_type` is exactly
  `"system_message"` and every key is in the allowlist. Because `tool_name`, `tool_info` and
  `subagent_info` are not in the allowlist, a step carrying any of them is refused.
- `_broker_gemini_stream_result`, tooled branch: admit an inert step before the step-type check,
  and count it as `provider_stream_system_steps`. That metadata key is emitted only when
  `tooled`, so the no-tool route's metadata stays byte-identical.
- `_stream_rejection_walk`: treat an inert step as recorded, using the same helper.

### Tests
- In `tests/test_gemini_seat_session_tools.py`:
  - Split `test_agys_other_step_types_stay_refused`.
  - Add refusal cases: `subagent_info`, `tool_name` (refused and valid), `tool_info`, an
    unlisted key (`usage`, `text`, a sentinel), and a non-`DONE` shape that keeps the allowlist
    (this one is accepted).
  - Add a dev0-shaped fixture.
  - Add the no-tool route's unchanged behaviour.
  - Add a mutation test: widening `_JAILED_GEMINI_STEP_TYPES` lets a tool-carrying
    `system_message` through.
- In `tests/test_gemini_stream_rejection_1823.py`, remove `system_message` from
  `_AGY_UNRECORDED_STEP_TYPES`, and add a record-parity case for the bare and non-inert shapes.
- In `tests/test_agy_qci.py`, re-pin `VALIDATOR_CLOSURE_SHA256["agy_validator_v1"]`. Leave
  `VERDICT_VECTOR_SHA256` and `QUALIFICATION_VALIDATOR` untouched.

## Documentation impact
- `advisor_board/CONTRACTS.md`, the jailed-route bullet: name the admitted inert `system_message`.
- `CHANGELOG.md`, Unreleased: add a "Fixed" entry.

## Order
Red tests first, then the helper and the parser, then the walk, then the re-pin, then the docs.

## Verification
Run each file serially (`-p no:xdist`) under `timeout 600`, gated on memory.max − anon ≥ 6 GiB
and PSI full avg10 ≤ 1:
- `tests/test_gemini_seat_session_tools.py`
- `tests/test_gemini_stream_rejection_1823.py`
- `tests/test_agy_qci.py`
- `tests/test_panel_invoker.py -k "gemini_stream or broker_gemini"`, non-live selections only

## Acceptance criteria
- [ ] A dev0-shaped tooled stream returns `rc == 0` with `provider_stream_system_steps == 3`.
- [ ] A `system_message` carrying `subagent_info`, `tool_name` or `tool_info`, or an unlisted
      key, is refused with `gemini_seat_subagent_or_unknown_event`. `error_message`, `unknown`
      and `subagent` are still refused.
- [ ] `test_agy_qci.py::test_the_guard_holds_at_this_validator` passes, with the verdict vector
      unchanged and no `QUALIFICATION_VALIDATOR` bump.
- [ ] The widening mutant fails a test.
