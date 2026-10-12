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
- **Worker bound:** at most four live workers per `_Calls` group, including abandoned workers. A worker holds a semaphore permit until it actually exits; abandoning a call does not free the permit. At the cap refuse before creating/enqueueing another call with the existing operation-timeout code. Completed workers release permits. Cleanup remains bounded; if it cannot obtain a worker, keep the fenced journal entry for reaping instead of claiming destruction. This limits accumulation without introducing an operator setting or claiming that Python threads can be forcibly stopped.
- **Result bound:** check result byte length against the request's cap before JSON parsing, accepting a result or recording `completed`. Oversize uses the existing lost-after-launch failure and normal cancel/release path, with no raw result in diagnostics and no replay. The backend remains responsible for bounding capture before constructing the result; this is the runtime backstop.
- **Budget parsing:** unset/blank retains 600/300 seconds. Parse whole integers; malformed values raise `SandboxConfigError("sandbox_config_invalid")` without echoing the input. Preserve negative-to-zero clamping and zero values. Clamp positive integers to `floor(threading.TIMEOUT_MAX / 2)` per setting before float conversion, keeping their sum within the platform's finite wait limit. This is a numeric safety ceiling, not a new routing/lifetime policy. Other `_env_int` consumers stay unchanged.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `_serve` / `_Calls` — add the fixed live-worker semaphore, release on actual worker exit, rollback on failed thread startup, and caller-context propagation. Preserve bounded waiting and cancellation; do not reuse an abandoned queue.
- `_Walk._sealing` — call the existing bounded mechanism; map timeout to the existing budget/timeout refusal as appropriate and cancellation to the existing cancel/release transition. Preserve validation and the post-callback budget check.
- `run_placed` — enforce `output_cap_bytes` before `_echoes`, accepted result and runtime completion receipt.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `admit_wait_s` / `transfer_allowance_s` — share one private placement-duration parser for the decisions above. Do not change other configuration readers.

### `phase-loop-runtime/tests/test_placement_driver.py` (modify)
- Add production-entrypoint controls for a hung seal, cancellation while sealing, late seal result after release, preserved caller context and the no-answer-reservation boundary.
- Add worker-cap controls using events: hold abandoned workers, count dispatched callbacks, prove the next call refuses without starting a worker, unblock workers, and prove a subsequent bounded call can run. Include cleanup-cap exhaustion keeping fenced journal evidence. Always unblock owned test workers in teardown.
- Add exact-cap and cap-plus-one results; assert the latter never reaches `_echoes`, never records `completed`, and follows cancel/confirmed-release or retained-unconfirmed-release paths.
- Change malformed-budget expectation from silent default to typed failure; cover defaults, blanks, whitespace, zero, negatives, malformed/nonfinite/decimal inputs and huge integer saturation. Invalid configuration must produce zero admission/commit/execute effects.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` (modify)
- Document the sealing/worker/result backstops and exact budget input behavior next to the placement implementation notes. Keep C1–C12 and ladder tables intact. State that cleanup at the worker cap remains unconfirmed and retains fencing; the cap does not attest backend destruction.

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

Each new behavioral control must fail under its corresponding narrow mutation: direct/unbounded sealing; freeing a permit on abandon; skipping the worker cap; parsing oversize before rejecting; reverting malformed-input refusal or saturation. Record mutation outcomes without persisting mutated source or imposing future commit identities.

## Acceptance criteria

- [ ] A never-returning seal and caller cancellation finish within their tested bounds, fence/release, and never execute a late returned spec — narrow driver suite and direct-seal mutation.
- [ ] Existing C7 boundary outcomes, context propagation, no additional answer reservation and all ladder orderings pass — driver and ladder suites.
- [ ] Four live workers bound accumulation; cap refusal dispatches no callback; actual exits restore capacity; unconfirmed cleanup retains fenced journal evidence — driver worker-cap controls and cap/abandon mutations.
- [ ] A result at the cap follows ordinary validation; cap-plus-one never parses or records completion and follows existing final-launch cleanup — driver result controls and cap mutation.
- [ ] Placement duration inputs have the declared default/refusal/clamp behavior, finite safe sum and zero remote effects on malformed configuration — driver/policy controls and parser mutations.
- [ ] Nonlocal leg flag stays false; existing lease/placement/ladder/inventory/local-equivalence regressions and required hosted checks pass; panel CR, independent approval and president bind the actual source — recorded verification/review receipts.
