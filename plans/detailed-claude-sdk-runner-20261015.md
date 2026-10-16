---
type: detailed
status: planned
owner_skill: codex-plan-detailed
related_issues: [agent-harness#1391]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_claude_sdk_runner.py tests/test_phase_loop_claude_route_selection.py tests/test_phase_loop_claude_channel_security.py tests/test_phase_loop_claude_agent_view_dispatch_409.py tests/test_claude_seat_subscription_proof_1444.py tests/test_subscription_scrub_xai_864.py tests/test_launcher_exec_supervisor.py tests/test_launcher_liveness.py tests/test_launchspec_golden.py tests/test_phase_loop_pipeline_bridge.py tests/test_claude_transport_seam.py tests/test_panel_claude_print_route.py"
  verification_status: not_run
---

# Detailed plan: optional subscription-proven SDK route for the solo Claude runner (Stage 3a)

## Task

Add an explicit `PHASE_LOOP_CLAUDE_ROUTE=sdk` runner route using the official Python
`ClaudeSDKClient`, with the existing installed CLI and proven subscription context.
The [proposed Stage 3 amendment](decision-claude-sdk-subscription-route-20261015.md)
defines admission and rollout. This plan prepares implementation; it does not
ratify that amendment or change runtime behavior.

Use one bounded implementation for the explicit route. Default promotion and
print billing correction are a later unit, so their route-contract changes cannot
hide inside SDK integration. Preserve Channel/Agent View/print and the panel TUI
fallback. Do not activate SDK panels, rename panel functions, or delete Channel.

## Research summary

At input `0b8444e820aba08a27e68cb1ad0d2c9a0efe2d92`, `launcher.py` owns route
selection, launch specs, auth preflight, generated Claude bundles, output parsing
and the synchronous supervised launch boundary. `claude_channel_sidecar.py` owns
the route-result vocabulary. `runner.py` consumes `LaunchResult`; it needs no new
agent loop. Panel transport ownership is separate and remains with PANELSPLIT/PANEL.

The [Python SDK reference](https://code.claude.com/docs/en/agent-sdk/python)
provides explicit CLI selection, configuration, permissions, typed messages and
interrupts. Pin the optional dependency to the inspected release
`claude-agent-sdk==0.2.167`, upstream commit
`c10b52c674e5c709c7263544b38e8a5dad10e01d`; its Python floor matches the runtime's
3.10 floor. Dependency installation must still prove compatibility.

The [pinned subprocess transport](https://github.com/anthropics/claude-agent-sdk-python/blob/c10b52c674e5c709c7263544b38e8a5dad10e01d/src/claude_agent_sdk/_internal/transport/subprocess_cli.py)
merges inherited environment with SDK options and launches its own version probe.
Therefore run the SDK in a separate, already-scrubbed helper process under the
existing executor supervisor. Use public SDK APIs; do not monkeypatch SDK internals
or the runner's global environment. The SDK CLI remains that helper's descendant.

## Changes

Paths below are relative to `phase-loop-runtime/` unless stated otherwise.

### `pyproject.toml` (modify)

Add optional extra `claude-sdk = ["claude-agent-sdk==0.2.167"]`. Ordinary installs
and non-SDK routes must work without it. The implementation must verify package
availability without importing SDK code during module import or dry run.

### `src/phase_loop_runtime/launcher.py` (modify)

- `CLAUDE_ROUTE_ALIASES`, `resolve_claude_route`, `build_claude_launch_spec`: add
  `sdk` / `claude_sdk` aliases with reason `explicit_sdk`. Preserve unset interactive
  Channel selection, CI explicit-route refusal, invalid-route refusal and legacy
  branches. SDK requests are solo only; reject `review`, `subagent` and `agent_team`
  before bundle materialization, credential probes or subprocess creation.
- Build a helper command using `sys.executable -m phase_loop_runtime.claude_sdk_adapter`.
  Carry model, effort, cwd, tool lists, approval posture, bundle placeholders and
  output schema explicitly. The helper accepts only this adapter's defined flags,
  not arbitrary CLI overrides. On live launch resolve `claude` through the child
  PATH to an absolute path and pass `--cli-path`; absent CLI/extra refuses the
  route. A dry run produces metadata without resolving credentials or starting SDK.
- Reuse `_resolve_command_context` / `_claude_bundle_paths` to materialize the
  existing settings, plugin, agents, MCP and context. Keep the existing bundle's
  prompt instruction when context-file delivery is selected; otherwise send the
  rendered prompt on helper stdin. Remove positional prompt content from helper
  argv. Materialized files share the existing cleanup ownership.
- `launch_with_spec`: keep `run_auth_preflight`'s subscription/caller checks and
  repeat the child-context check at the SDK boundary, including direct callers
  that skipped the runner's preflight. Reject caller-supplied credentials before
  scrubbing so scrubbing cannot turn that rejection into acceptance. Use
  `scrub_subscription_env` for the helper, then the existing `launch` path with its
  cwd, heartbeat, quiet/stall thresholds, stream flag, caller ID and lease authority.
  No custom unsupervised process manager. Enable the existing ephemeral monitor
  when no persistent log was requested.
- Feed the helper's normalized stream into the existing Claude output/closeout
  extraction. Require a successful terminal result independently of assistant
  text and exit code. Preserve structured-output validation, timeout/interruption
  fields and descendant cleanup evidence when returning through `_result_with_spec`.
- Keep SDK prelaunch billing posture `unknown`; stamp the metadata-only
  `claude_route_result` with `subscription_local` / `subscription_included` only
  after the subscription and init guards pass. Prelaunch posture is a statement of
  incomplete proof, not a conflicting charge estimate. Preserve legacy print's
  current metadata until its separate correction is implemented.

### `src/phase_loop_runtime/claude_sdk_adapter.py` (create)

- A small helper entrypoint, not a new inference loop. Import SDK lazily after
  confirming its process environment is scrubbed. Parse the parent's fixed
  options; read the prompt from stdin. Use the supplied absolute `cli_path` for
  both auth/capability checks and `ClaudeAgentOptions`; forbid bundled discovery.
- Prove the helper's actual login with `seat_credentials.login_subscription_proven`
  and an auth-status probe of that CLI under the same environment/config directory.
  This probe is of the helper's credential context, not the separately narrowed
  panel-seat profile; accept the corresponding logged-in first-party subscription
  shape and reject API/helper/console/alternate-provider shapes. Probe output is
  parsed privately, never emitted. Preserve `HOME` / `CLAUDE_CONFIG_DIR` from the
  selected login context. Do not inject or extract an access token.
- Construct public `ClaudeAgentOptions` with the selected model/effort, cwd/add_dirs,
  explicit `tools`, `allowed_tools`, `disallowed_tools`, generated settings/plugins,
  agents and MCP configuration, and `output_format` through `_claude_json_schema`.
  Select the `claude_code` system-prompt preset and the CLI's user/project/local
  setting sources explicitly, with the generated settings layered as before;
  an SDK's minimal default prompt must not silently replace the coding harness.
  Preserve the
  existing explicit bypass option; otherwise deny permission/input requests that
  cannot be satisfied headlessly. Do not rely on `allowed_tools` as a tool ceiling
  or on `can_use_tool` to intercept already approved calls. Preserve generated MCP
  isolation and do not enable ambient connectors. Never pass `--bare`; use the
  CLI's nonpersistent-session flag and capability-check required flags.
- Use `async with ClaudeSDKClient(...)`, `query(...)`, `receive_response()` and
  `interrupt()`. Validate init via `SystemMessage.data`; apply the amendment's
  missing/conflicting-init and auth-drift rules. Emit selected, redacted JSON-lines
  events in the existing stream-json shapes. Forward actual message progress,
  final `result` / `structured_output`, and a small allowlisted route receipt.
  For schema-bound actions, validate `structured_output` and serialize it into the
  normalized `result` text consumed by the existing closeout extractor; do not
  fall back to an assistant fragment when the structured result is missing or
  invalid. For other actions require the successful result's text. In either case,
  never dump dataclasses, arbitrary stderr, environment or init payloads.
- Require `ResultMessage` success and valid action output. Assistant fragments,
  missing result, auth drift and disconnect are failures. Use existing route
  statuses (`blocked`, `error`, `done`); adapter reasons distinguish dependency,
  CLI, subscription, auth drift and incomplete-result failures. On termination,
  interrupt and close the SDK; the outer supervisor remains responsible for
  signal escalation and reaping the whole descendant tree. No retry through another
  transport and no infinite heartbeat when the SDK is quiet.

### `src/phase_loop_runtime/claude_channel_sidecar.py` (modify)

Add `claude_sdk` only to `CLAUDE_ROUTE_NAMES`. The quoted contract and authorized
vocabulary delta are in amendment section 2. Keep envelope fields and all other
literal sets unchanged. Route receipts contain references and booleans, not
completion text. The actual completion remains executor output.

### `tests/test_claude_sdk_runner.py` (create)

Use SDK-client doubles for event cases and a fake executable with a fake SDK
package for real helper-process cases. Synthetic credentials never leave the test.
Cover the production `build_launch_spec` → `launch_with_spec` → helper path:

- extra absent; CLI absent; dry run offline; explicit aliases; non-solo/review
  rejection before any subprocess; selected CLI wins over a decoy bundled CLI;
- parent containing synthetic forbidden credentials is rejected; scrubber unit
  coverage plus a real child with a synthetic hostile ambient environment prove
  the SDK inference child and SDK version probe cannot re-inherit removed keys;
  a live helper uses the same config/login as the proof, and the parent environment
  remains byte-identical;
- options parity, context/bundle cleanup, no prompt/token in argv, no widening
  through SDK defaults, permission refusal, and explicit bypass parity;
- init none/missing/contradictory, auth/billing/organization retry events, valid
  structured result, invalid closeout, nonzero result, assistant-only EOF and
  stderr/output redaction;
- actual supervisor cancellation, lease revocation, stall and SIGTERM clean up
  helper plus fake CLI descendant, including no-log launches. SDK events advance
  progress; no event means the existing stall detector can fire;
- route receipt round-trip with the extended vocabulary, refusal as unknown
  billing, and success provenance without reporting a measured account charge.

### `tests/test_phase_loop_claude_route_selection.py` (modify)

Add explicit SDK route/receipt assertions; retain existing default, CI, Channel,
Agent View, invalid and print cases. Do not regenerate the existing golden to
hide an unrelated change. SDK cases live in the new test; legacy golden cases
must remain identical.

### `README.md` (runtime package; modify)

Document the optional extra, explicit selector, supported solo scope, required
subscription login, no silent fallback, qualification evidence and rollback by
selecting an existing route. Update the frozen capability statement only through
the ratified amendment/canonical-doc owner; do not rewrite a packaged historical
snapshot as if it were its upstream source.

## Documentation impact

The proposed amendment carries the normative route extension. At ratification,
the governance owner appends the Stage 3 pointer to the earlier ruling and updates
the carried v11 citation through its amendment/seal workflow. Frozen v10 and
panel skills remain unchanged. Runtime operator instructions change with Stage 3a.

## Dependencies and order

1. Ratify and land the proposed amendment before enabling SDK execution. Coordinate
   the route vocabulary extension with consumers that strictly validate the frozen
   envelope. No SDK result may be labeled as an older route for compatibility.
2. Implement the optional adapter and integration; verify narrowly, then the
   standalone suite and installed package. This does not wait for PANELSPLIT and
   does not claim `panel_invoker.py`, panel modules or `president_adapter.py`.
3. Qualify explicitly on claw in a disposable repository, then review the actual
   implementation head under the existing governed process before landing.
4. Default promotion and print billing correction get a separate bounded plan
   after that receipt exists. Panel SDK activation is a separate PANEL-owned task.

## Verification

Commands below are prescribed for implementation, **not run during this planning
task**. Use an interpreter with the runtime/test dependencies and SDK extra.

1. Run `automation.suite_command` from repository root. Existing integration skips
   do not count as exercised SDK paths; the new production-path tests must run.
2. From `phase-loop-runtime`, run
   `PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration'`.
3. From that directory run `python -m build`. Install the built wheel in a clean
   Python 3.10+ venv with its `claude-sdk` extra; run
   `python -m phase_loop_runtime.claude_sdk_adapter --help` from outside the checkout
   with `PYTHONPATH` unset, and repeat the synthetic helper-process tests against
   that installation. A second install without the extra must still import the
   launcher and refuse SDK cleanly. Check Python 3.10 dependency resolution.
4. Add an opt-in `tests/test_claude_sdk_runner.py::test_live_subscription_qualification`
   gated by `PHASE_LOOP_SDK_LIVE_PROOF=1`. Invoke it with
   `PHASE_LOOP_SDK_LIVE_PROOF=1 PYTHONPATH=src:tests python -m pytest -q tests/test_claude_sdk_runner.py::test_live_subscription_qualification`.
   It builds real runner specs against a disposable repo, completes an authoring
   turn and an execution turn with schema-valid closeout, observes cancellation,
   and writes `plans/evidence/claude-sdk-stage3/qualification.json` in the outer
   checkout. Report actual SDK/CLI versions, selected model/effort, auth booleans,
   init proof, terminal outcome, cleanup receipt and test outcome only. No tokens,
   raw init, prompt, transcript or account identity. Missing credentials skips;
   a skip is not qualification. Retain the existing maintainer billing observation
   from agent-harness#1391 rather than claiming an account-ledger measurement.

The live receipt supplements the automated suite; it does not replace any gate
or amend criteria by proxy. No new proxy-evidence mechanism is proposed.

## Acceptance criteria

- [ ] EC-REVIEWTRUTH-18 — only the transport-exception slice is in scope; proven
  by the ratified amendment reference and native-host/SDK-seat refusal regressions
  in `automation.suite_command`. This unit does not close the carried goal.
- [ ] The explicit solo SDK route runs through the production launcher, selected
  CLI and existing supervisor; proven by `automation.suite_command`.
- [ ] Credential, configuration, capability and terminal-result failures are
  closed without widening or fallback; proven by `automation.suite_command`.
- [ ] Legacy defaults, CLI routes and panel selectors retain their current
  behavior; proven by route, golden and panel tests in `automation.suite_command`.
- [ ] Wheel-only operation and optional dependency absence behave as specified;
  proven by verification step 3.
- [ ] A real subscription-backed authoring/execution turn and cancellation have
  a redacted receipt; proven by verification step 4 with a non-skipped pass.
