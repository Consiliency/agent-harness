# Detailed plan: president launches under heartbeat monitoring + broker isolation (agent-harness#1001)

## Task
agent-harness#1001: the PRESROUTE president adapter (agent-harness#998) launches every non-native rung
without `review_monitor` (1800 s deadline, silence/flat-CPU kill stay active), without the
`ParentUnixBroker`, and without `isolated_network` egress, while its authorization declares
`child_network_egress=False` etc. Carry `monitoring_policy` through the president operation using the
same broker / lease / monitor / egress machinery as review seats; heartbeat_only => no model-thinking
deadline, no silence kill, no expiring namespace holder. Do not borrow the review authorization.

## Research summary
Review seats: `_default_spawn` (panel_invoker) stages `review-bundle.md` + `review-instructions.md`,
acquires `_sandbox_egress.isolated_network(timeout_s=None under a monitor)`, sets
`_EGRESS_LAUNCH_PREFIX`, derives a single-use `ReviewLegAuthorization` from the leased review
authorization (`derive_review_leg_authorization`), and runs the provider through
`ParentUnixBroker.run_credentialless_client(adapter, deadline_s=None, cancel_event=monitor.cancel)`;
`_ReviewMonitor` (panel_invoker ~209) gates off the deadline/stall branches in
`_run_leg_with_liveness` / `_run_claude_tui_session`. Constraints: the broker accepts only
`ReviewLegAuthorization` and requires a LEASE under heartbeat_only; `PresidentIsolationAuthorization`
has no lease lifecycle and mints `canonical_repo_sha256=""` without a repo (the broker refuses "");
frozen `test_president_wiring.py:491` forbids the review operation identity for the president; the
3-site `launch_provider` pin scans panel_invoker only; backing.py forbids raw `threading.Thread`.

## Changes
### `advisor_board/backing.py` (modify, additive where possible)
- `PresidentIsolationAuthorization` — add `monitoring_policy` + lease registration (mirror
  `_remember_lease` / activate / close) — the broker needs an active lease under heartbeat_only.
- `derive_president_leg_authorization(authorization, prompt, *, harness, model, deadline_s,
  canonical_repo_authority)` — add — mints a leg authorization carrying operation
  `public_board_president.v1`, `input_sha256 = sha256(prompt)`, `instructions_sha256 =
  sha256(president instruction)`, and the lease's route budget.
- `ParentUnixBroker.__init__` / `_leg_operation_active` — modify — accept the president leg type
  (same seal/contract checks; operation must be exactly one of the two sealed identities).
- `_president_repo_digest` — heartbeat (and any brokered) president launch without a canonical repo
  is refused with the real reason (fail closed), not minted as "".
### `president_adapter.py` (modify)
- `PresidentInvoke._launch` — route every non-native rung through a new brokered president spawn:
  stage prompt/instructions read-only, acquire egress, derive leg authorization, build
  `_ReviewMonitor` (seat position = rung index, stream dir, operation cancel), run via the broker.
  Bounded keeps today's behaviour. Native Claude heartbeat refusal stays explicit.
- An injected-seam predicate mirroring `_has_injected_review_execution_seam` so the frozen SL-0
  tests that patch `launch_provider` keep their shape.
### `panel_invoker.py` (modify)
- invoke_board: pass `cancel_event` / invocation id / stream dir to the president seam it builds.
### `tests/test_president_heartbeat_1001.py` (create) — tests-first; mirror
  `test_review_monitor_policy.py` (real broker fixture, silence survival, cancel joins provider,
  egress-unavailable stays degraded, pre-cancelled never launches) for the president.

## Documentation impact
- `advisor_board/CONTRACTS.md` — ABDPRESROUTE rung-routes bullet — modify — brokered + monitored.
- `CHANGELOG.md` — add.

## Dependencies & order
Land agent-harness#1004 first (it rewrites `PresidentInvoke`, `build_president_invoke`, binding
sites). Write RED tests now against main; production edits after rebasing onto #1004.
Landing: native Opus president only (maintainer ruling 2026-09-23), since the route under repair
cannot preside over its own fix.

## Verification
- `PYTHONPATH=src:tests python -m pytest -q tests/test_president_heartbeat_1001.py` RED on main.
- The #1001 call-boundary probe: every non-native rung shows monitor present, deadline None, a
  non-empty egress prefix, a broker constructed; zero provider processes.
- Frozen PRESROUTE corpus + `test_review_monitor_policy.py` + `test_the_real_launch_carries_the_prefix.py`
  + `test_egress_prefix_crosses_the_broker_thread.py` green; bare-env subset vs main control.

## Acceptance criteria
- [ ] Under `heartbeat_only`, sol/grok/gemini (and claude outside Claude Code) launch with a
      `_ReviewMonitor`, `deadline_s=None`, no silence kill — proven by the #1001 probe as a test.
- [ ] Each such launch holds a non-empty egress prefix and runs through `ParentUnixBroker` with a
      president (not review) leg authorization — proven by a real-broker test.
- [ ] Unavailable isolation or a missing canonical repo is a typed refusal naming the reason; no
      provider process starts.
- [ ] Cancellation joins the provider and child; a pre-cancelled monitor never launches.
