---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1222, agent-harness#1166, agent-harness#1253]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_seat_launch_factoring.py tests/test_panel_leg_status_detail_1096.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_filesystem_view.py tests/test_seat_profiles.py tests/test_seat_credentials.py tests/test_seat_credential_refresh.py tests/test_seat_login_wait_a3_1166.py tests/test_seat_login_wait_board_context_r12.py tests/test_seat_owner_round1_1282.py tests/test_seat_jail_live_d8.py tests/test_finding_F002.py tests/test_finding_F004.py tests/test_sandbox_placement.py tests/test_seat_sandbox_permissions.py tests/test_seat_owner_notices.py tests/test_seat_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py tests/test_review_monitor_policy.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: factor the seat launch closure and the seat credential source, with no behaviour change (agent-harness#896)

## Task

To run a seat on another host with the same code, two things that are closed over the
launching host today must become callable with their inputs passed in:

1. the body of `_parent_infer` in `panel_invoker._default_spawn`, which launches the
   provider for a brokered seat;
2. the place a seat's credential comes from.

This unit does both and nothing else. No seat runs anywhere new, no request format exists
yet, the driver flag is untouched, and every local launch behaves exactly as before. It is
its own unit because it rewrites the attested launch site and the credential path, and a
reviewer must be able to check "nothing changed" on its own.

The work it prepares for is described in
`plans/detailed-remote-seat-placement-896-20261010.md` (the driver). This unit does not
depend on the driver plan and can land in parallel with it.

## Research summary

- **The closure.** `_parent_infer` is defined inside `_default_spawn`'s brokered branch. It
  calls `_prepare_jailed_claude` then `_exec_jailed_claude_leg`, or `_exec_claude_tui_leg`,
  or `_exec_leg`, and folds their failure details and notices into `leg_detail`,
  `gemini_detail` and `seat_notices`.
  - **What it closes over:** the leg and whether it is jailed; the staged directory, bundle
    and instructions; the sealed prompt, which is rendered **outside** it; the model, effort
    and environment; the timeouts; the review monitor and the broker's quiescence latch;
    the review authorization; the broker's evidence dictionary; the session name; and the
    leg's seat id, which is **assigned only for a jailed leg** and read only on that branch.
  - **What it reads without closing over it:** the egress launch prefix is a context
    variable read inside the body; its callees read the spawn counter, the redaction list
    and the board-cancel event the same way. After the move these are still set by the
    caller's context. That is right for this unit; they are listed here because a later
    caller on another host has to set them itself.
  - **What leaves it as an exception:** the quiescence error; any exception from `_exec_leg`
    for a harness other than Gemini; `gemini_broker_diagnostic_invalid`; and anything from
    the two Claude routes that is not a typed refusal. The outer handler types these.
- **Credentials are read in two places in the code this unit moves, and in more places it
  does not move.**
  - Moved: the seat-launch owner route reads through `seat_profile`: its inner `credential`
    helper calls `_seat_credential(home, …)`; its body reads grok's agent id with
    `_seat_credential` directly; and for Claude it calls
    `seat_credentials.resolve_claude_seat_credential` with a margin **and the seat's
    `env`**. `home` is `env["HOME"]`, or for the Gemini heartbeat profile a home derived
    from that profile's mounts. Branches: codex, Claude, grok, Gemini, opencode.
  - Moved: the **jailed** Claude seat does not pass through `seat_profile`.
    `_prepare_jailed_claude` calls `resolve_claude_seat_credential` itself.
  - **Not moved, and they stay on the launching host:** the seat-mode preflight; the login
    wait; the presence check in the route decision; the read behind the ignored-override
    notice (`_ignored_override`); the launch-time jailed check (`_seat_jailed_at_launch`);
    and the Gemini freshness check, which reads the operator's token file before the host
    refresh. None of these goes through the credential source.
  - `seat_profile` tolerates a missing credential file, and a Claude refusal, only for the
    administrative role, the first by inspecting the cause chain of the error.
  - The values registered for output redaction come from the same narrowing.
- **How existing tests reach this code.** Several tests replace
  `seat_credentials.resolve_claude_seat_credential` on the module and expect the launch
  path to see the replacement, and one asserts the `HOME` the resolver was given
  (`tests/test_seat_profiles.py`, `tests/test_seat_notices.py`). `_prepare_jailed_claude`
  has positional callers in tests.
- **What pins the launch, and what does not.**
  - Plan 1a's local-equivalence golden
    (`tests/fixtures/sandbox_placement_896/local_equivalence.json`) drives the two
    **unbrokered** branches. It never enters the brokered branch, so it does not execute
    `_parent_infer`.
  - The launch-spec golden covers executor launch specs. The seat-jail profile digests and
    the falsifier layout identity describe the jail's arguments and the staged layout.
  - **The tests that run the real closure** are `tests/test_panel_leg_status_detail_1096.py`
    (a fake broker transport over the production `_parent_infer`) and
    `tests/test_agy_integrity_seat_admission.py` (whose named mutation is in the closure's
    Gemini branch).
  - `tests/data/seat_launch_references.json` counts launch and file references per
    function. The closure holds no counted reference of its own, so moving it moves no row.
    `seat_profile` holds counted references, and its narrowing does move.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_LegInference` — add — a small record of what `_parent_infer` produces today: status,
  text, the failure detail (the Gemini one and the others kept distinct, as today), the
  notices it appended.
- `_infer_leg_here(...) -> _LegInference` — add — the body of `_parent_infer`, moved
  without change, with what it closed over passed as arguments. The sealed prompt is an
  argument; where it is rendered does not move. The seat id is an optional argument, read
  only on the jailed branch. **It adds no exception handler:** every exception that leaves
  the body today leaves this function with the same type and arguments.
- `_parent_infer` — modify — builds the arguments and calls `_infer_leg_here`, then applies
  the result to the same local variables as today.
- `_prepare_jailed_claude` — modify — takes `credential_source` as a **keyword argument with
  a default** and asks it for the Claude credential instead of calling the resolver
  directly.
- `_narrow_seat_credentials(harness, source, *, home, env, role)` — add — everything
  `seat_profile` reads and narrows today: the inner `credential` helper's work, grok's
  agent id, the Claude decision, the administrative role's two tolerances with the same
  cause-chain test, and the redaction values. It returns the files, the Claude token and
  the redaction values. `seat_profile` — modify — takes `credential_source` as a keyword
  argument with a default and consumes that result. The Gemini freshness check and host
  refresh stay in `seat_profile`, before the narrowing, unchanged.
- `LOCAL_LOGIN_SOURCE` — add — the only implementation in this unit, **here beside
  `_seat_credential`**, so no counted reference crosses modules. Its file read is today's
  `_seat_credential(home, relative)`. Its Claude read calls
  `seat_credentials.resolve_claude_seat_credential` **looked up on the module at call
  time**, with the margin and the `env` it was given, so a test that replaces the resolver
  still sees its replacement and the same store is read.

### `phase-loop-runtime/src/phase_loop_runtime/seat_credentials.py` (modify)
- `SeatCredentialSource` — add — a protocol with two reads: a credential file by home and
  relative path, and the Claude seat credential for a margin and an environment.
- **Deliberately not added here.** A placed seat will need a third read: the login's own
  access token and expiry, ignoring any stored override. Main's resolver returns the
  override first, and `login_seconds_left` and `await_login_margin` return early when an
  override applies, so the two reads above cannot supply it. That read belongs to the
  placed-seat follow-on plan, with its consumer; adding it here would land code that
  nothing calls.

### `phase-loop-runtime/tests/test_seat_launch_factoring.py`, `tests/fixtures/seat_launch_factoring/closure_recording.json` (create); `tests/data/seat_launch_references.json` (modify)
- The recording — add — taken **on the base, before any code moves**, by the test module's
  own recorder, for each branch of the closure and each outcome listed under
  "Verification". It holds two kinds of fact:
  - **what comes out:** the status, text, details, notices and broker-evidence keys
    `_parent_infer` produces, or the type and arguments of the exception that leaves it;
  - **what happens on the way, in order:** each credential read (which read, for which
    path or margin, with which `HOME`), each acquisition the launch depends on (the seat
    id, the egress prefix as read), and the launch itself as the provider is started: its
    argument list, the names of its environment variables, and its bind list. Secret
    values are recorded as digests, never as values.
- The falsifiers under "Verification".
- The inventory — modify — the rows that move from `seat_profile` to
  `_narrow_seat_credentials` and `LOCAL_LOGIN_SOURCE`, all within `panel_invoker`. The
  closure's move changes no row. The PR body lists every moved row.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — one
  sentence under SEATOWNER and one under SEATJAIL: a seat's credential is read through a
  credential source, and the only source is the operator's own login stores.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`, marked internal.
- Every other document — none: no behaviour changes.

## Dependencies & order
1. No dependency on the driver plan.
2. It edits the launch site and `seat_profile`, which the 0.7.27 seat fixes also edit. It
   starts from a base that contains them and does not merge an older one over them.
3. No agy route-core file is edited (`gemini_heartbeat.py`, `agy_qualification.py`,
   `agy_provenance.py`). If the Gemini seat's freshness check or host refresh cannot be
   left exactly where it is, the implementer stops and reports before editing one.
4. Nothing a seat sandbox permits changes: binds, capabilities, namespaces and network
   rules are the same lists in the same order.
5. Order: write the recorder and take the recording on the base (this is the RED-capable
   instrument: run it against a deliberately altered closure first and keep that log);
   capture the identities and goldens; move `_parent_infer`'s body alone and re-check;
   then the credential source alone and re-check.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_seat_launch_factoring.py tests/test_panel_leg_status_detail_1096.py \
  tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_filesystem_view.py \
  tests/test_seat_profiles.py tests/test_seat_credentials.py \
  tests/test_seat_credential_refresh.py tests/test_seat_login_wait_a3_1166.py \
  tests/test_seat_login_wait_board_context_r12.py tests/test_seat_owner_round1_1282.py \
  tests/test_seat_jail_live_d8.py tests/test_finding_F002.py tests/test_finding_F004.py \
  tests/test_sandbox_placement.py tests/test_seat_sandbox_permissions.py \
  tests/test_seat_owner_notices.py tests/test_seat_notices.py \
  tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py \
  tests/test_launchspec_golden.py tests/test_review_monitor_policy.py
ruff check .
```

Run on Python 3.12 and 3.10. Each case is control-green and red under its mutation.

**The closure.** The recording is the proof; it is driven through the production
`_parent_infer` with a fake broker transport, as `tests/test_panel_leg_status_detail_1096.py`
does.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Each branch (jailed Claude, non-jailed Claude, `_exec_leg` for codex, grok and Gemini), success and each typed failure | Status, text, details, notices and broker-evidence keys equal the recording taken on the base | Drop a notice in the fold; lose `gemini_detail`; alter when `leg_detail` is cleared |
| The ordered sequence for each branch: credential reads, acquisitions, then the launch with its argument list, environment names and bind list | Equal to the recording, element for element and in the same order | Swap two credential reads; resolve the Claude credential before the tree re-hash in the jailed branch; add one environment name; add or reorder one bind |
| Each exception that leaves `_parent_infer` on the base (the quiescence error; a non-Gemini `_exec_leg` exception; `gemini_broker_diagnostic_invalid`; an untyped exception from each Claude route) | Leaves `_infer_leg_here`, and `_parent_infer`, with the same type and arguments; the leg ends with the same status as on the base | Build the result inside a broad `except` |
| A leg that is not jailed | Runs with no seat id supplied | Build every argument eagerly |
| The two existing tests that run the real closure | Pass unchanged | — |

**The credential source.**

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| An injected source that differs from the host's stores, for each branch of `seat_profile` (codex, grok, a non-jailed Claude, Gemini with each of its two homes, opencode) and for the **jailed** Claude | The seat receives the injected source's bytes, grok's agent id included; a spy on the host's login stores records no read by the moved code. For Gemini the freshness check still reads the host's token file, by design, and that read is the only one recorded | Leave the direct resolver call in `_prepare_jailed_claude`; read grok's agent id outside the source |
| The default source | The bytes a seat receives equal the base's, for each harness, with the real file shapes of each CLI's store | Narrow twice |
| A test replaces `seat_credentials.resolve_claude_seat_credential` on the module | The launch path calls the replacement, with the seat's `env` (the existing assertions on `HOME` hold) | Bind the resolver when the source is created |
| The administrative role with a missing credential file, and with a Claude refusal; the review role with the same | Tolerated; refused, with the same code as on the base | Wrap the source's errors so the cause chain changes |
| Redaction, per harness | The values registered for redaction equal the base's, and an output containing each is redacted | Drop one value from the returned list |
| A refusal after the Claude credential is resolved | Still carries the credential's notices as siblings of its one code (agent-harness#1253) | Drop the notices in the source |
| `_prepare_jailed_claude` and `seat_profile` called as existing tests call them | Work without the new argument | Make the argument positional or required |

**Identities.**

| Case | Expected |
|---|---|
| Plan 1a's local-equivalence golden | Matches unchanged. It covers the two unbrokered branches only and is not the proof for the closure. |
| Launch-spec golden; seat-jail profile digests; falsifier layout identity | Equal before and after, recorded in the PR |
| Inventory | Only rows named in the PR body move, all within `panel_invoker`; per-module totals are equal; the closure's move changes no row |

## Acceptance criteria
- [ ] For every branch of the closure and every outcome in the recording taken on the base
  (jailed Claude, non-jailed Claude, `_exec_leg` for codex, grok and Gemini; success, each
  typed failure, and each exception that leaves it), `_infer_leg_here` through
  `_parent_infer` reproduces the recording: what comes out, and the ordered sequence of
  credential reads, acquisitions and the launch's argument list, environment names and
  binds. The recorder's own red log, one entry per named mutation, is in the PR.
- [ ] With an injected credential source, the jailed Claude seat and every `seat_profile`
  branch receive that source's bytes with no read of the host's login stores by the moved
  code; with the default source the bytes and the redaction values equal the base's.
- [ ] Every existing test in `automation.suite_command` passes without modification,
  including those that replace the resolver on its module and those that call
  `_prepare_jailed_claude` positionally.
- [ ] Plan 1a's golden, `tests/test_launchspec_golden.py`, the seat-jail profile digests
  and the falsifier layout identity are equal before and after;
  `tests/data/seat_launch_references.json` differs only by rows that move within
  `panel_invoker`.
- [ ] `git diff --stat` lists no file among `gemini_heartbeat.py`, `agy_qualification.py`,
  `agy_provenance.py`.

## Maintainer decisions

None. This unit changes no behaviour.

## Execution Policy

- execute: effort=high, reason=a behaviour-preserving move of the attested launch site and the credential path; the proof is a recording taken before the move
