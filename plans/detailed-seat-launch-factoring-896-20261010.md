---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1222, agent-harness#1166, agent-harness#1253]
builds_on: plans/detailed-remote-seat-placement-896-20261010.md
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_seat_launch_factoring.py tests/test_sandbox_placement.py tests/test_seat_sandbox_permissions.py tests/test_seat_owner_notices.py tests/test_seat_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py tests/test_review_monitor_policy.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: factor the seat launch closure and the seat credential source, with no behaviour change (agent-harness#896, P3)

## Task

To run a seat on another host with the same code, two things that are closed over the
launching host today must become callable with their inputs passed in:

1. the body of `_parent_infer` in `panel_invoker._default_spawn`, which launches the
   provider for a brokered seat;
2. the place a seat's credential comes from.

This unit does both and nothing else. No seat runs anywhere new, no request format exists
yet, the driver flag is untouched, and every local launch is byte-identical before and
after. It is its own unit because it rewrites the attested launch site and the credential
path, and a reviewer must be able to check "nothing changed" on its own.

The slice is described in `plans/detailed-remote-seat-placement-896-20261010.md`. This unit
does not depend on P1 or P2 and can land in parallel with them.

## Research summary

- **The closure.** `_parent_infer` is defined inside `_default_spawn`'s brokered branch. It
  calls `_prepare_jailed_claude` then `_exec_jailed_claude_leg`, or `_exec_claude_tui_leg`,
  or `_exec_leg`, and folds their failure details and notices into `leg_detail`,
  `gemini_detail` and `seat_notices`. It closes over: the leg and whether it is jailed; the
  staged directory, bundle and instructions; the sealed prompt, which is rendered
  **outside** it; the model, effort and environment; the timeouts; the review monitor and
  the broker's quiescence latch; the leg's seat id and egress prefix; the review
  authorization; the broker's evidence dictionary; the session name.
- **Credentials are read in two places, not one.**
  - The seat-launch owner route (codex, grok, a non-jailed Claude, the sealed Gemini seat)
    reads through `seat_profile`, whose inner helpers call `_seat_credential(home, …)` and,
    for Claude, `seat_credentials.resolve_claude_seat_credential`.
  - The **jailed** Claude seat does not pass through `seat_profile`.
    `_prepare_jailed_claude` calls `seat_credentials.resolve_claude_seat_credential`
    itself and hands the token to `seat_jail.token_pipe`.
  - Two more reads stay where they are and are not touched: the seat-mode preflight and the
    login wait, both before staging, both on the launching host.
- **What pins the launch.** Plan 1a's local-equivalence golden
  (`tests/fixtures/sandbox_placement_896/local_equivalence.json`); the launch-spec golden;
  the seat-jail profile digests and the falsifier layout identity;
  `tests/test_seat_sandbox_permissions.py` (the jailed prepare);
  `tests/data/seat_launch_references.json`, which counts launch and file references **per
  function**, so moving code moves rows.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_LegInference` — add — a small record of what `_parent_infer` produces today: status,
  text, the failure detail, the notices it appended.
- `_infer_leg_here(...) -> _LegInference` — add — the body of `_parent_infer`, moved
  without change, with everything it closed over passed as arguments. The sealed prompt is
  an argument; where it is rendered does not move.
- `_parent_infer` — modify — builds the arguments and calls `_infer_leg_here`, then applies
  the result to the same local variables as today.
- `_prepare_jailed_claude` — modify — takes a `credential_source` argument and asks it for
  the Claude credential instead of calling the resolver directly.
- `_narrow_seat_credentials(harness, source, env, role)` — add — the narrowing that
  `seat_profile`'s inner `credential` helper and its Claude branch do today, returning the
  files, the Claude token and the redaction values. `seat_profile` — modify — takes a
  `credential_source` argument and consumes that result.

### `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py` (modify)
- `SeatCredentialSource` — add — a protocol with two reads: a credential file by relative
  path, and the Claude seat credential for a margin.
- `LOCAL_LOGIN_SOURCE` — add — the only implementation in this unit: today's reads of the
  operator's stores. Every call site passes it, explicitly or by default.

### `phase-loop-runtime/tests/test_seat_launch_factoring.py` (create); `tests/data/seat_launch_references.json` (modify)
- The falsifiers under "Verification".
- The inventory rows that move from `_default_spawn` to `_infer_leg_here`, and from
  `seat_profile` to `_narrow_seat_credentials`. The PR body lists every moved row and
  shows that the totals per module are unchanged.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — one
  sentence under SEATOWNER and one under SEATJAIL: a seat's credential is read through a
  credential source, and the only source is the operator's own login stores.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`, marked internal.
- Every other document — none: no behaviour changes.

## Dependencies & order
1. No dependency on P1 or P2.
2. It edits the launch site and `seat_profile`, which the 0.7.27 seat fixes also edit. It
   starts from a base that contains them and does not merge an older one over them.
3. No agy route-core file is edited. If the Gemini seat's host refresh cannot be left
   exactly where it is, the implementer stops and reports before editing one.
4. Nothing a seat sandbox permits changes: binds, capabilities, namespaces and network
   rules are the same lists in the same order.
5. Order: capture the identities and goldens on the base; move `_parent_infer`'s body
   alone and re-check; then the credential source alone and re-check.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_seat_launch_factoring.py tests/test_sandbox_placement.py \
  tests/test_seat_sandbox_permissions.py tests/test_seat_owner_notices.py \
  tests/test_seat_notices.py tests/test_seat_reference_inventory.py \
  tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py \
  tests/test_review_monitor_policy.py
ruff check .
```

Run on Python 3.12 and 3.10. Each case is control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Local equivalence | Plan 1a's golden (call sequence, provider argv, `provider_cwd_sha256`) matches unchanged on each launch branch | Acquire egress inside `_infer_leg_here` |
| Launch-spec golden; seat-jail profile digests; falsifier layout identity | Equal before and after, recorded in the PR | — |
| Each branch through `_infer_leg_here` (jailed Claude, non-jailed Claude, `_exec_leg`), success and each typed failure | The same status, text, detail and notices `_parent_infer` produced on the base, compared against a recording taken there | Drop a notice in the fold |
| An injected credential source that differs from the host's stores, for codex, grok, a non-jailed Claude and the **jailed** Claude | The seat receives the injected source's bytes; a spy on the host's login stores records no read | Leave the direct resolver call in `_prepare_jailed_claude` |
| The default source | The bytes a seat receives equal the base's, for each harness, with the real file shapes of each CLI's store | Narrow twice |
| A refusal after the Claude credential is resolved | Still carries the credential's notices as siblings of its one code (agent-harness#1253) | Drop the notices in the source |
| Inventory | Only rows named in the PR body move; per-module totals are equal | — |

## Acceptance criteria
- [ ] Plan 1a's local-equivalence golden and `tests/test_launchspec_golden.py` pass
  unchanged, and the seat-jail profile digests and the falsifier layout identity are equal
  before and after.
- [ ] With an injected credential source, the jailed Claude seat and each owner-route seat
  receive that source's bytes and no read of the host's login stores is recorded.
- [ ] `tests/data/seat_launch_references.json` differs only by moved rows, with equal
  per-module totals.
- [ ] `git diff --stat` lists no file among `gemini_heartbeat.py`, `agy_qualification.py`,
  `agy_provenance.py`.

## Maintainer decisions

None. This unit changes no behaviour.

## Execution Policy

- execute: effort=high, reason=a behaviour-preserving move of the attested launch site and the credential path; the proof is that nothing changed
