---
type: detailed
status: planned
owner_skill: codex-plan-detailed
related_issues: [agent-harness#1391]
automation:
  suite_command: >-
    cd phase-loop-runtime && PYTHONPATH="$PWD/src:$PWD/tests" python -m pytest -q -m 'not dotfiles_integration' tests/test_claude_sdk_runner.py tests/test_phase_loop_claude_route_selection.py tests/test_phase_loop_claude_channel_security.py tests/test_phase_loop_claude_agent_view_dispatch_409.py tests/test_claude_seat_subscription_proof_1444.py tests/test_subscription_scrub_xai_864.py tests/test_launcher_exec_supervisor.py tests/test_launcher_liveness.py tests/test_launchspec_golden.py tests/test_phase_loop_pipeline_bridge.py tests/test_claude_transport_seam.py tests/test_panel_claude_print_route.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_adapter_skill_references.py tests/test_seat_reference_inventory.py tests/test_seat_launch_helpers_trusted.py tests/test_ci_xdist_adoption.py tests/test_local_check.py tests/test_python_floor_1546.py tests/test_ci_chronology_scope.py tests/test_seat_jail_prerequisites_1357.py tests/test_verification_interpreter_guard_221.py tests/test_sandbox_staging_1147.py
  verification_status: not_run
---

# Detailed plan: optional subscription-proven SDK route for the solo Claude runner (Stage 3a)

## Task

Add an explicit `PHASE_LOOP_CLAUDE_ROUTE=sdk` runner route using the official Python
`ClaudeSDKClient`, with the existing installed CLI and proven subscription context.
The [proposed Stage 3 amendment](decision-claude-sdk-subscription-route-20261015.md)
defines admission and rollout. This plan prepares implementation; it does not
ratify that amendment or change runtime behavior.

Default promotion and print billing correction are separate. Preserve Channel,
Agent View, print and the panel TUI fallback; panel SDK activation and refactoring
remain outside this unit.

## Research summary

At input `0b8444e820aba08a27e68cb1ad0d2c9a0efe2d92`, `launcher.py` owns selection,
preflight, bundles, supervision/output; `claude_channel_sidecar.py`
owns route vocabulary. `runner.py` consumes `LaunchResult`; PANELSPLIT/PANEL owns
panel transports.

Pin the optional dependency to the inspected release
`claude-agent-sdk==0.2.167`, upstream commit
`c10b52c674e5c709c7263544b38e8a5dad10e01d`; its Python floor matched the runtime's
3.10 floor at planning time. Upstream agent-harness#1546 now requires Python 3.12;
dependency installation and verification must prove compatibility with that floor.

The [pinned subprocess transport](https://github.com/anthropics/claude-agent-sdk-python/blob/c10b52c674e5c709c7263544b38e8a5dad10e01d/src/claude_agent_sdk/_internal/transport/subprocess_cli.py)
merges inherited environment with SDK options and launches its own version probe.
Therefore run the SDK in a separate, already-scrubbed helper process under the
existing executor supervisor. Use public SDK APIs; do not monkeypatch SDK internals
or the runner's global environment. The SDK CLI remains that helper's descendant.

## Changes

Paths below are relative to `phase-loop-runtime/` unless stated otherwise.

### `pyproject.toml` and `uv.lock` (modify)

Add optional extra `claude-sdk = ["claude-agent-sdk==0.2.167", "markdown-it-py==4.2.0"]`. Ordinary installs
and non-SDK routes must work without it. Verify package availability without
importing SDK code during module import or dry run.
Regenerate `uv.lock` with `uv lock`; verify locked synchronization with the extra.

### `src/phase_loop_runtime/launcher.py` (modify)

- `CLAUDE_ROUTE_ALIASES`, `resolve_claude_route`, `build_claude_launch_spec`: add
  `sdk` / `claude_sdk` aliases with reason `explicit_sdk`. Preserve unset interactive
  Channel selection, CI explicit-route refusal, invalid-route refusal and legacy
  branches. Reject SDK `request.action == "review"` or requested mode in
  `{"subagent", "agent_team"}` before degradation, bundles, credential probes or subprocesses.
- Build the helper command with
  `seat_uid.trusted_module_argv("phase_loop_runtime.claude_sdk_adapter", ...)`,
  using the parent's imported installation and the existing isolated bootstrap.
  Carry model, effort, cwd, tool lists, approval posture, bundle placeholders and
  output schema explicitly. The helper accepts only this adapter's defined flags,
  not arbitrary CLI overrides. On live launch resolve `claude` through the child
  PATH to an absolute path and pass `--cli-path`; absent CLI/extra refuses the
  route. A dry run produces metadata without resolving credentials or starting SDK.
- Reuse `_resolve_command_context` / `_claude_bundle_paths` to materialize the
  existing settings, plugin, agents, MCP and context. Keep the existing bundle's
  prompt instruction when context-file delivery is selected; otherwise send the
  rendered prompt on helper stdin. Remove positional prompt content from helper
  argv. For `log_path=None`, allocate temporary bundle storage before resolving
  placeholders, pass it through the monitored launch, and clean it up afterward.
- `launch_with_spec`: keep `run_auth_preflight`'s subscription/caller checks and
  repeat the child-context check at the SDK boundary, including direct callers
  that skipped the runner's preflight. Reject caller-supplied credentials before
  scrubbing so scrubbing cannot turn that rejection into acceptance. Use
  `scrub_subscription_env` for the helper, then the existing `launch` path with its
  cwd, heartbeat, quiet/stall thresholds, stream flag, caller ID and lease authority.
  No custom unsupervised process manager. Enable the existing ephemeral monitor
  when no persistent log was requested.
  For SDK, share the helper's offline context-admission check with
  `run_auth_preflight` before its probe loop; a parent probe must not precede it.
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
  Establish personal Pro/Max class from local credential metadata before any
  credential-bearing CLI operation; the subscription boolean alone is insufficient.
  Reject Team/Enterprise, profile-based, remote-policy-eligible or unknown contexts.
- Before that probe, resolve and bind effective settings as amendment condition 3
  requires, including the always-read global config and host/cached managed inputs.
  Probe and SDK use the same bound private context; `setting_sources=[]` disables
  only user/project/local loading. Refuse unbindable sources rather than treating
  one read or local-file absence as proof. Preserve permission precedence and
  project instructions. Stamp CLI probes with `child_scratch_env`.
- Construct public `ClaudeAgentOptions` with the selected model/effort, cwd/add_dirs,
  explicit `tools`, `disallowed_tools`, generated settings/plugins,
  agents and MCP configuration, and `output_format` through `_claude_json_schema`.
  Use the `claude_code` system-prompt preset. Match `build_claude_command` and
  `_claude_permission_mode(action, bypass_approvals)`; leave `allowed_tools=[]`.
  Authoring's `acceptEdits` must not gain implicit Bash auto-approval. Deny prompts
  that cannot be satisfied headlessly; callbacks cannot revoke prior approvals.
  Set `strict_mcp_config=True` and stamp `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in the
  helper environment; an empty MCP map is insufficient. Use public `extra_args`
  for `--no-session-persistence` and bypass-only flags the existing oracle emits.
  Never pass `--bare`; capability-check the required flags.
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

Use client doubles for message cases, plus the pinned installed SDK transport
with a fake CLI for credential-free subprocess cases. Never replace the SDK's
environment merge/version probe in the latter. Synthetic credentials stay private.
Cover the production `build_launch_spec` → `launch_with_spec` → helper path:

- extra absent; CLI absent; dry run offline; aliases; action/mode rejection,
  including `action="review"` with `claude_execution_mode="solo"` and authoring-plus-team
  before degradation or subprocesses;
  selected CLI wins over a decoy bundled CLI;
- parent containing synthetic forbidden credentials is rejected; scrubber unit
  coverage plus the real pinned `SubprocessCLITransport` observe both `-v` and
  inference fake-CLI environments through the production helper launch; removing
  helper scrubbing must fail this test without contacting a provider;
  a live helper uses the same config/login as the proof, and the parent environment
  remains byte-identical;
- hostile supported settings/global-source cases and changed/unbound inputs refuse
  before the credential-bearing probe/connection, even if login/init would pass;
  remote-policy-eligible/unknown local metadata refuses; a personal-context positive
  control succeeds. Verify connector/memory controls with the pinned transport and
  preserve unrelated permissions/instructions. Do not assume arbitrary global keys
  are effective settings without CLI evidence;
- options parity against runner CLI argv, no-log bundle success/cleanup, no
  prompt/token in argv, `allowed_tools=[]`, permission/bypass parity, and helper
  package provenance after changing cwd;
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

### Owner-approved execution scope addendum — 2026-10-17

Include `tests/test_agent_cli_scratch_inventory_1147.py` to declare the new helper's
auth and capability probes as relocated launches using `child_scratch_env`, and
repository-root `CHANGELOG.md` for the contributor-required user-visible release
note. The owner approved these two required adjuncts during implementation; the
targeted suite includes the inventory checks. This adds no scratch exception,
transport authority or acceptance waiver. The ratified subscription amendment and
acceptance criteria remain unchanged.

### Verification inventory during owner-authorized continuation

Include `tests/data/seat_launch_references.json` to classify the SDK helper's
existing probe and I/O references under the static audit's existing roles. This
records the implementation without an audit exception or a regenerated golden
masking unrelated behavior. Integration verification also includes the upstream
adapter-reference tests and `tests/test_seat_reference_inventory.py`.

### CI dependency and helper-launch verification

Include repository-root `.github/workflows/test.yml` and
`ci/dagger/src/agent_harness_ci/main.py` so hosted and offloaded suite installs
include the optional SDK extra. Keep the ordinary package dependency optional and
the clean-room core-only path intact. Update the existing install-line consumers
in `tests/test_ci_xdist_adoption.py`, `scripts/local_check.py` and
`tests/test_local_check.py`, retaining their worker, restart and tool pins.
SDK-dependent production refusal tests require the optional dependency and
sandbox; dependency-absence and offline dry-run tests remain executable without
the extra. Both helper entrypoints use the existing trusted-module launcher.
Verify the existing trusted-helper suite and the new production provenance
regression as part of the same targeted run, including the local CI mirror tests.
Validate that the runtime's frontmatter parser and suite resolver read the complete
prescribed command. These repairs preserve the declared admission and acceptance
requirements.

### Current upstream Python floor

Integrate agent-harness#1549 without changing its Python 3.12 minimum, single-lane
CI, chronology selection or dependency posture. Keep the SDK optional and pinned;
regenerate its lock entries on the upstream lockfile and verify installation,
targeted tests and wheel behavior on Python 3.12. Include the upstream Python-floor,
chronology-scope and jail-prerequisite consumer tests in the targeted suite.

### Owner-approved linked user instructions — 2026-10-17

Extend this implementation for the selected user `CLAUDE.md` file and its explicit
unconditional instruction imports, including linked files. The owner approved
preserving these instructions, regression testing and reviewed live qualification.
Modify only `src/phase_loop_runtime/claude_sdk_adapter.py`,
`tests/test_claude_sdk_runner.py`, the runtime `README.md`, repository `CHANGELOG.md`,
this plan and the required explicit I/O entries in
`tests/data/seat_launch_references.json` for this extension. Include the already-owned
`pyproject.toml` and `uv.lock` for the exact-pinned optional Markdown parser and its
test-group dependency. Repeated structural approximations omitted imports or
refused ordinary examples; use the parser's CommonMark block source maps instead.
This is an implementation dependency within the approved complete-capture scope.
The ratified admission conditions, optional SDK
pin, route vocabulary, acceptance criteria and required full/live gates remain.

In `_instructions`, grant link/import handling only to the selected user
`CLAUDE.md` and files it explicitly imports. Preserve complete parent and imported
text in deterministic order in the existing private instruction snapshot, used by
both probe and SDK contexts. Resolve links to regular UTF-8 files owned by the
operator or root, enforce bounded reads and a four-hop import limit, deduplicate
canonical targets, and refuse dangling/cyclic links, import cycles, unsafe file
types, changed capture inputs and unsupported import syntax before authentication.
Limit cumulative user-file reads to 32 MiB and user-file visits to 256, including
repeated aliases; refuse without truncation. Validate every transitive path and
depth even when its text was already captured. Admit only known ordinary local
filesystems through the opened handle before reading; require bytes read to equal
descriptor size, rejecting pseudo-files. Repeated targets must match their first
capture, and revalidate captured identities and aliases before returning.
Limit the complete UTF-8 snapshot, including project/rule bodies and joiners, to
64 KiB with no embedded NUL; the pinned SDK passes it as one CLI argument.
Read through a stable descriptor and reject link replacement or in-place changes
during capture. After capture, host changes must not alter the frozen instructions.
For a relative import through a linked file, admit only when the selected and
canonical parent paths resolve it to the same target; otherwise refuse rather
than guessing. Bind each validated import target and both relative interpretations
through capture. Expand `~/` only against the admitted target HOME; named-user
expansion is unsupported. Canonical inline `@path` examples, email addresses and
quote-wrapped paths remain literal. Fenced/import-candidate combinations and
whitespace-preceded `@` within inline spans are unsupported because inspected native
and CommonMark interpretations conflict. Underscore-adjacent and escaped visible
candidates refuse before dependency resolution.
Use `markdown-it-py==4.2.0` with the explicit CommonMark preset and no plugins or
rendering. Keep the original CR/LF-normalized scanning text and raw import grammar;
never scan rendered text, decoded entities or token children as the import source.
Only raw source ranges proved to be fenced code or supported inline code may be
masked; candidate-free indented code may also be excluded. Reference definitions
and other non-rendered source remain accounted for.
Confine ordinary inline-code matching to parser-provided inline block line ranges;
retain conservative raw-candidate guards for escapes, HTML/terminators, brackets,
indentation and pipes, including GFM ambiguity. Refuse unsupported or unmatched
backticks and unfenced indented import-like text. Preserve source/token boundaries
when masking so code removal cannot concatenate a different import. Preserve
original snapshot bytes. Parser conformance alone does not establish equivalence
with native Claude; require fresh regression, adversarial and actual-layout review.
Reject snapshot-size/NUL violations before parsing, and refuse parser nesting at
its truncation boundary or overlapping/invalid processing maps.
In candidate-bearing files, refuse raw triple-marker syntax combined with HTML
blocks, lexical line-start HTML-like syntax after repeatable quote/list prefixes,
or raw reference markers, even when the parser emits no fence. Refuse any
candidate-bearing fence; other fences require an explicit compatible closer on
the final mapped raw line, with space/blockquote prefixes and trailing spaces only.
Require mapped extent to equal LF-counted parser body lines plus opener and closer;
never use token content to discover imports. Refuse native-closer-shaped interior
raw fence lines and candidate-bearing inline blocks with backticks inside matched
code spans or any matched multiline span. Check every span in such a block before
masking, including an earlier multiline span with no candidate: native-only block
splits can change later single-line span pairing. Preserve candidate-free multiline
examples, separate-paragraph complete capture, and the original multiline literal
body as an explicit unsupported before-probe/never-open case. Use normalized LF for
this structural check without changing original snapshot bytes.
Determine candidate-bearing scope for both inline ambiguity checks over each
enclosing run of raw non-blank lines, since native parsing can join CommonMark
blocks without a blank boundary. A blank line contains only ASCII spaces/tabs;
retain raw list/quote prefixes and other whitespace characters as non-blank.
Precompute group candidate flags in one source pass and inspect all flags touched
by each validated inline map. Do not discover dependencies from the grouped text
or broaden masking beyond the original mapped block. Keep separate-blank-boundary
literal/capture controls and before-probe/never-open native-join regressions.
Refuse a raw run containing a candidate, any backtick and any `<`, `[` or `]`.
Check the complete run before parsing rather than adding token-region or initial
HTML exceptions: links/titles can open on otherwise uninspected carrier lines.
This intentionally narrows support for initial-HTML/code mixtures. Preserve prior
HTML mixture bodies as typed unsupported before-probe/never-open cases; retain
the no-HTML blank-boundary literals, candidate-free multiline examples and real
imports separated from unrelated code/link/HTML examples by a blank line.
Preserve candidate-free internal-backtick examples and actual explicit
closers across blank bodies, CR/LF endings and EOF without a final newline.
Refuse possible URL/backtick ambiguity before inline masking. Keep the prior raw
HTML/reference and native-stripping limitations; do not claim full native emulation.
Existing project link, descendant, scoped-rule and managed-policy refusals remain.
The exact selected `config/AGENTS.md` may be accepted as a user dependency only
when explicitly reached and validated from the selected user file, even if HOME
is a project ancestor. This is not ambient AGENTS discovery: project-tree AGENTS,
HOME/AGENTS, unrelated ancestors and unreferenced config/AGENTS remain refused.

Inspect the selected user instruction file and only its explicitly declared
instruction dependencies privately for qualification; retain only path/hash/type
metadata in evidence. Do not print instruction text, modify dotfiles, strip policy,
copy authentication secrets or broaden project authority. The observed claw layout
has one unconditional `@AGENTS.md` dependency with the same canonical target from
both parent paths. Permission modes on its directories do not justify discarding
the instructions; preserve the snapshot boundary rather than changing that setup.

Add production-path regressions for the linked user file plus imported linked
instructions, deterministic load order/deduplication, literal examples, invalid
targets/imports/cycles, capture races and immutability after host retargeting.
Retain the existing project-link refusal test. Run the expanded SDK file first,
then the existing targeted command and installed-wheel checks. Obtain independent
review and fresh presidential actual-HEAD binding before live qualification. The
opt-in live test must restore actual read-only mount metadata hidden by the
ordinary suite's host-state fixture. This
extension does not waive the outstanding full standalone result or grant merge,
activation, default-promotion or panel-SDK authority.

### Reviewed baseline fixture corrections — 2026-10-18

Under the owner's continuing convergence authority, include
`tests/test_verification_interpreter_guard_221.py` and
`tests/test_sandbox_staging_1147.py`. Independent presidential intake reviewed the
concrete two-file patch (`93ff97f4f41c6d98b60cb7cfbd9dd378b2b4e759dfad702ac8d4d67a64a2e537`)
and supported-runner differential evidence: three inherited-environment failures
become passes. Nominal interpreter fixtures explicitly model absent versioned
executables while retaining real version probes, resolver and shim construction.
The default scratch-relocation fixture clears only its inherited `TMPDIR` and
`CLAUDE_CODE_TMPDIR`; explicit caller-override coverage remains unchanged.
Expanded whole-file verification exposed the same inherited-input assumption in
the default RAM-refusal fixture. Presidential follow-up intake agreed to clear
the same two variables there, retaining its failed-envelope and refusal-detail
assertions and the separate explicit-caller tests.
No production guard or scratch policy changes. Add both complete test files to
the targeted command and verify under the supported outer interpreter guards,
including inherited scratch values. The original full command remains required;
these controls do not replace it or grant live, activation or merge authority.

## Documentation impact

Ratification appends the amendment pointer to v11's cited ruling, preserving
roadmap bytes/seals and panel skills. Stage 3a updates runtime operator instructions.

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

1. From `phase-loop-runtime`, run `uv lock --check` and
   `uv sync --group test --extra claude-sdk --locked`. Run `automation.suite_command`
   from repository root. Integration skips do not exercise SDK production paths.
2. From `phase-loop-runtime`, run
   `PYTHONPATH="$PWD/src:$PWD/tests" python -m pytest -q -m 'not dotfiles_integration'`.
3. From that directory run `python -m build`. Install the built wheel in a clean
   Python 3.12+ venv with its `claude-sdk` extra; run
   `python -m phase_loop_runtime.claude_sdk_adapter --help` from outside the checkout
   with `PYTHONPATH` unset, and repeat the synthetic helper-process tests against
   that installation. A second install without the extra must still import the
   launcher and refuse SDK cleanly. Check Python 3.12 dependency resolution.
4. Add an opt-in `tests/test_claude_sdk_runner.py::test_live_subscription_qualification`
   gated by `PHASE_LOOP_SDK_LIVE_PROOF=1`. Invoke it with
   `PHASE_LOOP_SDK_LIVE_PROOF=1 PYTHONPATH="$PWD/src:$PWD/tests" python -m pytest -q tests/test_claude_sdk_runner.py::test_live_subscription_qualification`.
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
