---
type: detailed
status: planned
owner_skill: codex-plan-detailed
input_base_commit: a5e8565ddf350dad038ca382e26cbf9c7850f528
issues: [agent-harness#735, agent-harness#826]
related_issue: agent-harness#734
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests/test_review_monitor_policy.py phase-loop-runtime/tests/test_leg_liveness_monitor.py phase-loop-runtime/tests/test_panel_tui_liveness_188.py phase-loop-runtime/tests/test_panel_invoker_timeout_argv.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_backcompat.py phase-loop-runtime/tests/test_harden_evidence_verifier.py phase-loop-runtime/tests/test_skill_liveness_contract.py phase-loop-runtime/tests/test_skills_canon_parity.py"
  verification_status: not_run
  human_required: false
---

# Detailed plan: explicit heartbeat-only review monitoring

## Task

Honor an explicit operator instruction not to terminate model thinking by elapsed
time or silence, without weakening review isolation, admission expiry, cancellation,
or cleanup. Implement this as an opt-in runtime policy, not a larger timeout or a
local monkey patch. Existing callers retain their bounded behavior.

This is planning only; Default mode is active. No implementation, verification,
provider request, installation, or deployment has run for this plan.

## Research summary

The installed `panel_invoker.py` matches the inspected upstream source: omitting
`timeouts_by_leg` still enables the default backstop. `_default_spawn` passes that
same duration into native monitors, leg authorization expiry, and the credentialless
broker's response wait. A timer-only patch would therefore leave another kill path
or break the sealed authorization boundary. Execution-function replacement is
explicitly rejected outside sanctioned hermetic test fixtures.

Inputs: the base above; `panel_invoker.py`, `advisor_board/backing.py`, and `cli.py`
under `phase-loop-runtime/src/phase_loop_runtime/`; existing liveness and HARDEN
tests; `docs/agent-phase-convergence.md`; and the
[agent-harness#826 preflight report](https://github.com/Consiliency/agent-harness/issues/826#issuecomment-5734013778).
The local preflight receipt is `/tmp/chat-b1-review-preflight-389-35eo7pDd/preflight.json`.

## Scope and decisions

- Public keyword `monitoring_policy="bounded" | "heartbeat_only"` on
  `invoke_board`, and `--monitoring-policy` on `advisor-board`. Omission means
  `bounded`; an explicit `timeouts_by_leg` entry with `heartbeat_only` is an error,
  including non-finite/zero sentinel tricks. No environment-variable override.
- First supported heartbeat-only routes: brokered homebrew/subscription Claude
  TUI, Codex, and Grok. Gemini/agy, gateway/API-backed routes, capture mode, and
  legacy `invoke_panel` are unsupported. Gemini has a separate internal
  `--print-timeout`; do not guess a disabling value. Reject the entire incompatible
  requested board before availability/auth/session/provider effects. Do not drop
  or substitute a seat. The default four-vendor CLI board consequently refuses
  this opt-in until its unsupported route receives a separate repair; explicit
  supported boards remain callable through `invoke_board`.
- A heartbeat records observation, not proof that a remote model is working.
  Silence, flat CPU, or cosmetic TUI animation becomes `progress_unobserved`,
  never a kill instruction or a claim of provider health. Preserve existing
  genuine-progress detection and exact-session/current-turn verdict boundaries.
- `heartbeat_only` has no model wall-clock cap, silence cap, or automatic retry.
  One admitted attempt ends on its own completion/exit, typed terminal failure,
  explicit cancellation, or loss of its owning operation. An empty completed
  attempt stays empty; a later retry requires a fresh authorized operation.
- Keep finite local admission and teardown bounds. Use a 10-second admission
  window (matching the existing listener bound), measured from leg minting, and
  existing cleanup grace constants. These never terminate an admitted model merely
  because its response is slow. Cancellation is operation-scoped and idempotent.

Out of scope: proving provider-side request lifecycle or billing settlement
(`agent-harness#734`), Gemini support, new models/auth paths, installed-package
hot swaps, and all AI-stack/Fractal code or acceptance-state changes. Preserve
AI-stack release `0ff63a0` and unapplied rollback `928ce64` unchanged.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py` (modify)

- Add an immutable resolved monitoring-policy value alongside the existing
  authorization types. Bind requested/effective policy into board and leg
  capabilities and independently revalidate it at dispatch. Preserve the sealed
  factory, exact staged-input/instruction/canonical-repo bindings, route counts,
  and one-use claim. Do not put control authority into reviewer prose.
- Separate admission expiry from response waiting in `derive_review_leg_authorization`,
  `ParentUnixBroker.serve_once`, and `run_credentialless_client`. Bound acceptance
  and complete frame receipt; recheck expiry and operation ownership immediately
  before consuming the request, including a frame that straddles expiry. Clear
  the socket's admission timeout only after successful admission.
- During an admitted heartbeat-only request, poll child/operation cancellation
  without an aggregate elapsed-time cutoff. On cancellation, revocation, child
  failure, or parent interruption, cancel the provider, reap the namespace child,
  and join the server. Failed quiescence must remain non-success. Cover launch
  exceptions and partial setup as well as the normal wait path.
- Preserve the finite bounded-mode receipt. For the opt-in, record a null
  `operation_deadline_s` plus an explicitly versioned monitoring record; never
  manufacture a finite deadline. Authorization expiry remains finite and is
  identified as admission-only in that record.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- `invoke_board` performs pure policy/capability preflight before effectful work;
  `_default_spawn` independently checks the authorized policy. Unsupported or
  mismatched policy returns `UNAVAILABLE` with a stable diagnostic and zero effects.
- Thread the resolved policy through `_default_spawn`, `_exec_leg`, Claude's
  broker/TUI launcher, `_run_claude_tui_session`, and `_run_leg_with_liveness`.
  Preserve `_leg_deadline_from` and existing retry algebra for bounded callers;
  heartbeat-only bypasses both deadline and silence termination, not cancellation,
  typed startup failures, native exit, or post-leader-exit descendant cleanup.
- Extend the existing operation cancellation/quiescence mechanism rather than
  adding an unowned daemon. An explicit cancellation event wakes every monitor;
  parent SIGINT/SIGTERM follows the same cleanup path. Verify abrupt owner loss
  with a subprocess supervisor test; no provider process may escape ownership.
- Retain a run-local, metadata-only monitoring snapshot at the existing output
  directory, keyed by invocation and seat position (not collision-prone label).
  Schema `review_monitoring.v1` records requested/effective policy, admission and
  model deadlines, last genuine-progress age, observation state, and terminal
  reason. Update on the existing observation cadence using atomic replacement;
  no prompt, transcript, credentials, or environment values. Monitoring write
  failure is reported, never fabricated as a healthy heartbeat or successful
  evidence. Attach the final record to the result without altering legacy output.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)

- Parse the policy before composition. For heartbeat-only, perform the pure
  requested-board capability check before composition can probe vendor auth.
  Thread the policy into authorization and invocation; independently validate
  direct API calls. JSON opt-in output includes the monitoring record, including
  refusals. Default JSON shape remains unchanged.

### Integration with agent-harness#890

- Preserve launch_provider/run_provider and context-carrying broker threads,
  staged-tree/authorization checks before egress acquisition, and truthful sandbox
  facts. EgressUnavailable remains DEGRADED with its exception in detail.
- Extend `sandbox_egress.py` so heartbeat-only uses an owner pipe for namespace
  holder/uplink lifetime. Owner exit or cancellation closes the pipe and reaps both
  helpers; model waiting has no aggregate timer. Existing bounded callers retain
  their finite holder behavior. New launches use the common launch function.
- Compose network entry, provider PID ownership, and capability removal in that
  order. Verify real fixture providers still launch without firewall capabilities,
  and both namespace helpers exit on normal teardown and abrupt owner death.

### Tests (create/modify)

- Create `phase-loop-runtime/tests/test_review_monitor_policy.py` for the public
  policy contract, broker admission/response split, policy substitution/replay
  negatives, real-child cancellation and ownership, and metadata-only receipts.
  Use the existing sanctioned HARDEN fixtures, never global authorization bypasses.
- Extend `test_leg_liveness_monitor.py`, `test_panel_tui_liveness_188.py`, and
  `test_panel_invoker_timeout_argv.py` for virtual-clock survival beyond the old
  backstop and silence thresholds, current-turn-only completion, no automatic
  heartbeat-only retries, explicit cancellation, and unchanged bounded behavior.
- Extend `test_advisor_board_cli_legacy.py` for zero-effect unsupported/default
  board refusal and policy plumbing; extend `test_skill_liveness_contract.py`
  to enforce the distinction on every canonical/generated/packaged skill surface.

## Documentation impact and frozen contracts

Update `docs/advisor-board-capabilities-card.md` and append the policy contract to
`phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`. Modify the
four located canonical skills at
`skills-src/{codex,claude,gemini,opencode}/<harness>-advisor-board/SKILL.md`:
explicit no-deadline requests MUST select and preflight this policy, not merely
omit overrides. Explain unsupported boards and do not advertise remote-health
proof. Label the existing timeout/retry instructions as bounded-mode behavior.
Regenerate neutral and packaged skill copies using the existing two scripts;
do not hand-edit generated aliases or installed skill files.

Frozen protocol anchors read at the input base:

- `panel_invoker.py:184-191`: `"OK", "EMPTY", "TIMEOUT", "ERROR", "DEGRADED", "UNAVAILABLE"`.
- `advisor_board/backing.py:485-497`: request keys
  `{"schema","operation","nonce","harness","model","purpose","input_sha256"}`;
  response keys `{"schema", "status", "text"}`; response text is opaque prose.

Introduce no new literals or fields into those frozen status/wire vocabularies.
The new policy values and `review_monitoring.v1` are a separate opt-in contract.
Do not change observer event kinds to smuggle heartbeats through the frozen event
envelope. Preserve the EC-HARDEN-5 invariant; do not claim this bounded repair
completes that roadmap phase.

Record a narrowly scoped amendment beside EC-LEGLIFE-1/EC-LEGLIFE-2 in
`specs/phase-plans-v10.md`: the original bounded-mode assertions remain intact;
the new explicit opt-in waits until a real terminal event or cancellation and
must quiesce before returning. This semantic extension requires review, not an
unrecorded reinterpretation of “always returns.” Refresh plan/roadmap provenance
before any runner dispatch that consumes the amendment.

Provenance refresh uses `roadmap_reseal` for the current digest representations,
updates the affected plan headers, and appends `plan_current_authority.v1` records
sourced to agent-harness#892. Historical lifecycle, contracts, review receipts,
and authority entries are immutable. The RUNTIME grounding assertion separates
its original ancestral input from the current append-only authority; it must
still reject missing, rewritten, or mismatched bindings. This provenance-only
test amendment does not approve a changed RUNTIME SL-0 inventory or authorize
runner dispatch using an earlier test-review receipt. All prior phase statuses
remain unchanged; review of this candidate is still required.

## Dependencies & order

1. Freeze the policy distinction and roadmap amendment, then add failing controls
   in the owned worktree. Preserve unrelated concurrent work. Seven authored
   runtime/skill source files are in scope; generated copies are mechanical.
2. Implement authorization/admission, then cancellation-aware native/broker waiting,
   then CLI/receipts and guidance. Verify narrowly before the broader suite.
3. Retain an exact-head review packet with test evidence and mutation controls.
   Pre-register three review rounds maximum; delta re-review dissenting/unusable
   seats only, no cancel-on-first-blocker. Do not waive isolation or operator
   policy to bootstrap review. A source-isolated candidate may be evaluated only
   through its normal sealed authorization path after offline controls pass;
   it cannot self-certify its review or claim installed-runtime acceptance.
4. Publication, fresh-process installation, and the real AI-stack B1 board are
   a separate operational follow-through after review. No live package replacement
   inside an active review, no inference-service restart, and no automatic seat
   reduction. If the required board still includes Gemini, report that specific
   unsupported-route gate; do not mark the AI-stack review complete.

## Verification

Execution-only prerequisites: create a dedicated worktree `.venv` with
`python3 -m venv .venv`; install the local project and its test group into that
environment with the repo's dependency tooling. Do not use or mutate either the
installed phase-loop environment or AI-stack's serving environment.

After guidance edits, run the two existing generation scripts below, then the
frontmatter `automation.suite_command`. Its new
policy module must prove, using virtual clocks and finite test fixtures:

- Genuine-progress and silent/CPU-flat cases survive multiple old backstops;
  cancellation, native failure and current-turn completion still terminate.
- Admission before expiry may finish afterward; expired, replayed, changed-policy,
  wrong-route, wrong-input, and partial-frame requests never invoke inference.
- Policy failure causes zero availability/auth/session/provider/spawn effects,
  even with a forged factory or mismatched effective policy.
- Cancellation during setup, frame receipt, and response waiting; failed child;
  parent interruption/death; simultaneous completion/cancel; stubborn descendant;
  and failed provider quiescence never produce usable success or leaked children.
- Monitoring artifacts contain no review content or credentials. Terminal reasons
  distinguish policy refusal, user cancel, process exit/failure, and bounded expiry;
  silence remains observational. Legacy golden behavior stays unchanged.

Generation commands, followed by the broader checks after the focused suite:

```sh
.venv/bin/python phase-loop-runtime/scripts/regenerate_skills_bundle.py
.venv/bin/python phase-loop-runtime/scripts/sync_skills_bundle.py
PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests
git diff --check
```

Classify baseline failures and opt-in skips; never call skipped HARDEN evidence
producer/verifier work a production proof. Retain raw logs and a JSON summary
under `.phase-loop/review-monitor-policy/<run-id>/`. Demonstrate non-vacuity with
isolated test mutants restoring each old deadline/silence kill, dropping policy
binding, accepting expired admission, and suppressing cancellation/reaping; the
corresponding new controls must fail. Do not leave mutants in the candidate.
No live provider call or AI-stack inference is part of this offline acceptance.

## Acceptance criteria

- [ ] Explicit policy is bound end-to-end; unsupported/conflicting requests have
  zero effects — `test_review_monitor_policy.py` and `test_advisor_board_cli_legacy.py`.
- [ ] Heartbeat-only survives old elapsed/silence bounds without false health claims
  or retries — `test_review_monitor_policy.py`, `test_leg_liveness_monitor.py`,
  `test_panel_tui_liveness_188.py`, and `test_panel_invoker_timeout_argv.py`.
- [ ] Finite single-use admission and cancellation/ownership cleanup remain proven,
  including negative mutants — `test_review_monitor_policy.py`; preserve
  EC-HARDEN-5 regression coverage in `test_harden_evidence_verifier.py` and the full suite.
- [ ] Bounded behavior and frozen vocabularies remain compatible —
  `test_advisor_board_backcompat.py`, existing timeout tests, and the full suite;
  EC-LEGLIFE-1/EC-LEGLIFE-2 extension is explicit in the reviewed roadmap amendment.
- [ ] Requested/effective policy and terminal facts are durable and privacy-safe —
  `test_review_monitor_policy.py` and `test_advisor_board_cli_legacy.py`.
- [ ] Skill guidance cannot mistake omitted overrides for heartbeat-only compliance;
  generated copies agree — `test_skill_liveness_contract.py`,
  `test_skills_canon_parity.py`, and `git diff --check`.

Offline acceptance does not mean publication, deployment, four-vendor readiness,
or AI-stack B1 approval. Any later operational evidence must be retained separately
and imported through a runner-stamped plan amendment before downstream reliance.
