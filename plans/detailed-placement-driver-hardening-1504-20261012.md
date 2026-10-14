---
type: detailed
status: planned
owner_skill: codex-plan-detailed
input_base_commit: a1c3937e1fc74ee16e03ccd2c22a7d4c0fe17184
related_issues: [agent-harness#1504, agent-harness#896]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_driver.py tests/test_placement_lease.py tests/test_placement_ladder_model.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py"
  verification_status: not_run
---

# Detailed plan: harden the placement driver before the SSH backend

## Task

Complete agent-harness#1504's four driver obligations before a backend builds on the merged placement driver. Keep the launch flag false and preserve the SSH-first sequence, authorization, journal ownership, fencing, fixed execution end and runtime/backend evidence distinction. This is a prerequisite fix, not the SSH backend or an Omnigent architecture amendment.

No roadmap goal IDs apply. agent-harness#1504 defines this bounded scope. agent-harness#1506 constrains the future backend; agent-harness#1502 owns launch-site wiring and cancel/failed-execute precedence. Neither is closed by this change. The already-merged agent-harness#1489 is not duplicated. No cloud provider, reconnect, credential source, CLI launch, Python floor or agy route-core file changes.

## Research summary

`sandbox_placement._Walk._sealing` calls its callback directly, although admission already owns a remote reservation. `_Calls` bounds calls but creates another worker whenever a timed-out worker is abandoned, without limiting live abandoned workers. `run_placed` parses and accepts an `ExecResult.result` without applying `ExecSpec.output_cap_bytes`. The two placement budget readers use `_env_int`, which silently substitutes defaults for invalid input and has no upper limit before float conversion.

Use the existing `_Calls`, refusal codes, ladder transitions, release/fence path and production-entrypoint test fixtures. No new public parameter, setting or closed-vocabulary member is introduced.

The frozen basis is `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md:495`: “Every blocking call is bounded and interruptible.” C7 at lines 552–558 gives one admission-plus-transfer budget, with release independently bounded; lines 588–590 make a returned seal final only before that budget is spent. C8 at lines 658–662 keeps sealing and execute in the walk. Preserve `LADDER_TABLE` and its three-copy equality test; no ladder amendment is intended.

## Decisions

- **Seal bound:** run the callback through the existing bounded call mechanism with the remaining whole-walk budget and caller cancellation. Propagate the calling context's `contextvars` into the worker. A timed-out/cancelled callback can finish later, but its returned spec is ignored; the rung is fenced and released and never executes from that late result. Test the behavior through `place`, not just the helper.
- **Execute answer reservation (G7): do not reserve an additional fixed slice.** Preserve C7's existing whole-budget semantics: sealing may use the remaining budget; if it consumes the budget, release without execute. Otherwise execute gets the positive remainder capped by `ANSWER_BOUND_S`. A short acknowledgment bound can yield an uncertain launch; the existing final-launch/no-retry and confirmed-release rules govern it. Reserving a full extra slice would change the accepted ladder's boundary outcomes. The panel/president must explicitly reconcile this choice before implementation.
- **Worker bound:** at most four live workers per `_Calls` group, including abandoned workers. A worker holds a semaphore permit until it exits; abandonment does not free it. A private readiness helper creates/reuses the worker; `_Calls.run` and the final `start` local check share it. The helper raises operation-timeout for cap/startup failure. `_Walk._start` translates it to `local_check_failed` / `sandbox_placement_refused`, before probe or lease; later `_Calls.run` failures retain operation-timeout. This preserves C7's frozen class/code mapping. Undispatched probes never manufacture `unreachable` evidence (C3); cancellation retains precedence. Startup failure rolls back the permit. Cleanup exhaustion retains fenced evidence. The cap is per group, not process-wide or an operator setting.
- **Result bound:** require the declared bytes result and check its byte length against the request's cap before JSON parsing, accepting a result or recording `completed`. Nonbytes/oversize uses the existing lost-after-launch failure and normal cancel/release path, with no raw result in diagnostics or replay. The backend remains responsible for bounded capture before constructing the result; this is the runtime backstop.
- **Budget parsing:** unset/blank retains 600/300 seconds. Parse whole integers; malformed values raise `SandboxConfigError("sandbox_config_invalid")` without input-bearing exception chaining. Preserve negative-to-zero clamping and zero values. Saturate valid positive integers lexically at `floor(threading.TIMEOUT_MAX / 2)` before integer/float conversion, including strings beyond Python's digit-conversion limit and leading-zero padding. Their sum stays within the finite wait limit. This is a numeric safety ceiling, not a routing/lifetime policy. Other `_env_int` consumers stay unchanged.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `_serve` / `_Calls` / `_Walk._start` — add the fixed semaphore, release on actual exit, readiness helper and startup rollback. The final local check before `connecting` translates readiness failure to `local_check_failed` / `sandbox_placement_refused`; never false unreachability. `_Calls.run` keeps the helper's timeout for later calls. Copy each submitting caller's context; this does not propagate the leg caller through the separate heartbeat-thread boundary. Do not reuse an abandoned queue.
- `_Walk._sealing` — call the existing bounded mechanism; map timeout to the existing budget/timeout refusal as appropriate and cancellation to the existing cancel/release transition. Preserve validation and the post-callback budget check.
- `run_placed` — enforce `output_cap_bytes` before `_echoes`, accepted result and runtime completion receipt.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `admit_wait_s` / `transfer_allowance_s` — share one private placement-duration parser for the decisions above. Do not change other configuration readers.

### `phase-loop-runtime/tests/test_placement_driver.py` (modify)
- Add production-entrypoint controls for a hung seal, cancellation while sealing, late seal result after release, preserved caller context and the no-answer-reservation boundary.
- Add event-based worker-cap/recovery and startup rollback controls. Exercise `place` with two rungs whose admission/kill hang, and four hung admissions with otherwise successful cleanup. The third/fifth rung must record exactly `failed_locally` / `sandbox_placement_refused`, with remaining budget, no probe/lease and no unreachability claim. Startup failure has the same pair. Preserve cancellation/fenced leases; unblock workers in teardown. Add reused-context and multi-lease reaper controls.
- Add exact-cap, cap-plus-one and nonbytes results; rejected values never reach `_echoes` or record `completed`, and follow confirmed or retained-unconfirmed cleanup.
- Change malformed-budget expectation from silent default to typed failure; cover defaults/blanks/whitespace, zero, negatives, malformed/nonfinite/decimal inputs, very long integer saturation and zero padding. Invalid configuration produces zero remote effects and input-free diagnostics.

### `phase-loop-runtime/tests/test_placement_ladder_model.py` (modify)
- Add only the neutral worker-readiness method to `InlineCalls`; preserve the oracle, scripted events, table copies and every enrolled ordering. The adapter models instantly available workers; real abandonment is covered through `place` above.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` (modify)
- Document sealing/worker/result backstops, truthful local worker failure and exact budget input behavior beside implementation notes. Keep C1–C12 and tables intact. Cleanup exhaustion retains fencing; no backend destruction is attested.

### `CHANGELOG.md` (modify)
- Add one Unreleased entry for agent-harness#1504, explicitly retaining the disabled nonlocal leg driver.

### Plan, manifest and evidence (modify/create)
- This plan, `plans/manifest.json` and `plans/evidence/placement-driver-hardening-1504-20261012.json` — preserve actual source-bound plan/implementation reviews, prescript dispositions, verification and acceptance results. No raw credentials or runtime transcripts. Runner-owned verification output lives outside source under the authorized private run directory; export metadata/digests only.

## Documentation impact

Update the placement contract notes and changelog because malformed budget input changes from silently defaulted to a typed refusal. Defaults, negative clamping, zero values, the whole-budget ladder and the flag-off public path remain explicit. No CLI/schema/entry-point additions or generated agy qualification changes.

## Dependencies & order

1. Panel this exact plan using the owner's four harness seats, separate independent reviewer, manual tools-enabled Gemini and subscription Opus5.5 TUI, then Fable-only Opus president. Actual prescript distinguishes agent-harness#1504 blockers from agent-harness#1502/#1506, SSH/reconnect/placed-seat, Gemini and cloud follow-ons; no blanket waiver. Bound the review loop at three rounds as a scope/input checkpoint, not a waiver of required criteria.
2. Reproduce the current gaps with focused controls, then implement serially. No worker implementation fanout.
3. Batch narrow verification, then ladder/regression/inventory checks and lint. Preserve existing no-retry, journal-before-admit, owner death, fixed end, pending-release and local-equivalence cases.
4. Run actual-source panel CR and separate independent review, reconcile/rerun dissent, require the president and passing final-source hosted checks. Only then merge, verify main and close agent-harness#1504 with its four obligations proven. Keep unrelated/unmerged worktrees.
5. The SSH qualification plan may build on the resulting verified driver; it still requires its own panel and backend conformance, keeps the leg flag off, and carries agent-harness#1506 plus Q4/Q5. Signature/real placed-Claude and cloud gates are unchanged.

## Verification

Use an isolated environment matching the repository's current `requires-python`, frozen dependency install and absolute `PYTHONPATH` for child imports. Do not mutate global review tools or absorb the unrelated Python-floor PR. Capture commands, source and results in the private verification artifact and its repo metadata receipt.

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_driver.py
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_driver.py tests/test_placement_lease.py tests/test_placement_ladder_model.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py
ruff check .
```

Run the repository's supported Python lanes (currently 3.10 plus the broader hosted matrix) as applicable at execution; recheck current CI if the separately owned floor change lands. All ladder orderings stay enrolled. Required hosted suite/lint/wheel checks must pass; optional job skips are never reported as completed proof.

Each behavioral control must fail under its corresponding mutation: direct sealing; freeing abandoned permits/skipping the cap; bypassing the `start` readiness check or startup rollback; parsing rejected results; reverting malformed-input refusal/saturation. Record outcomes without persisting mutated source or pinning future history.

## Acceptance criteria

- [ ] A never-returning seal and caller cancellation finish within their tested bounds, fence/release, and never execute a late returned spec — narrow driver suite and direct-seal mutation.
- [ ] Existing C7 boundary outcomes, context propagation, no additional answer reservation and all ladder orderings pass — driver and ladder suites.
- [ ] Four live workers bound accumulation; cap/startup failure records `failed_locally` / `sandbox_placement_refused` before probe/lease, never false unreachability; exits/rollback restore capacity; cleanup retains fenced evidence — driver multi-rung/reaper and worker/readiness controls.
- [ ] An at-cap bytes result follows ordinary validation; oversize/nonbytes never parse or record completion and follow final-launch cleanup — driver result controls and cap mutation.
- [ ] Placement duration inputs have the declared default/refusal/clamp behavior, finite safe sum and zero remote effects on malformed configuration — driver/policy controls and parser mutations.
- [ ] Nonlocal leg flag stays false; existing lease/placement/ladder/inventory/local-equivalence regressions and required hosted checks pass; panel CR, independent approval and president bind the actual source — recorded verification/review receipts.
