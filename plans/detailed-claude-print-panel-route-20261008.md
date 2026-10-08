# Detailed plan: headless `claude -p` as the default route for Claude panel/president seats (Stage 1b)

## Task
Stage 1b of the owner-approved graduated Claude route. Non-native Claude panel, board and president
seats get a headless `claude -p --output-format stream-json --verbose` route, and it becomes the
default. The PTY TUI adapter stays as an explicit opt-in fallback. The run fails closed in-band if
it is not on subscription OAuth. Depends on Stage 1a
(`plans/detailed-claude-print-route-amendment-20261008.md`).

## Research summary
- **Single switch point.** All non-jailed Claude seats go through `_exec_claude_tui_leg`
  (`panel_invoker.py:9551`). It returns `(status, text)`. The deferral, version gate and auth gate
  run first (`_claude_subscription_auth_ok` `:6610`, called around `:9651`). Command building
  follows around `:9672`, and that is the switch point.
- **President.** `president_adapter.py:451-457` calls `_broker_claude_tui_command` and
  `_run_claude_tui_session` directly, so it needs its own branch.
- **Jailed seats.** `_exec_jailed_claude_leg` (`:9990`) is separate. It uses `bypassPermissions`
  and pipes the access token to the seat.
- **Output handling.** Status comes from `_classify_leg` (`:6688`) plus `_completion_ok`
  (`:2664`), applied to the review **text**. The file only carries that text, so the print route
  can feed the stream-json `result` text straight into the same classifier.
- **Reusable parsing.** `launcher._extract_claude_stream_json_text` (`launcher.py:3130`) already
  pulls `result`/`assistant` text. It does not look at `system/init` or `system/api_retry`.
- **Import safety.** `panel_invoker` already imports from `launcher` (`:82`), and `launcher`
  imports `panel_invoker` only lazily, so there is no import cycle.
- **Why not `build_claude_command`.** It (`launcher.py:662-708`) is tied to the runner: it injects
  plugin, settings, agents and MCP placeholders, `--add-dir <repo>`, and the prompt as an argv
  positional. Panel seats need the opposite: `--setting-sources ""`, `--strict-mcp-config`, an
  empty MCP config and agents, no `--add-dir`, the prompt on stdin, and the exact
  `--disallowedTools` list from `_broker_claude_tui_command` (`:6514`). So this plan reuses the
  shared pieces (the `-p --verbose --output-format stream-json` prefix and `_claude_json_schema`
  handling) and does not force the runner builder to serve both.
- **Selector name.** `PHASE_LOOP_CLAUDE_ROUTE` belongs to the runner (`launcher.py:813-850`). The
  panel needs its own selector.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_PANEL_CLAUDE_ROUTE_ENV = "PHASE_LOOP_PANEL_CLAUDE_ROUTE"` and `_panel_claude_route()` — add.
  Accepts `print` (the default) or `tui`. Any other value fails closed as `UNAVAILABLE` with
  detail `panel_claude_route_invalid`. It never silently falls back.
- `_CLAUDE_PRINT_MIN_VERSION = (2, 1, 259)` and its text constant — add. This is the minimum for
  `--permission-prompts none`. The print route checks it through `_claude_code_support_status`
  (`:6655`), which gains a `min_version` keyword. The TUI keeps `_CLAUDE_CODE_MIN_VERSION`.
- `_claude_print_seat_command(model, effort, *, brokered: bool)` — add. It builds:
  `claude -p --verbose --output-format stream-json --input-format text --model M --effort E`
  `--permission-mode dontAsk --permission-prompts none --setting-sources "" --strict-mcp-config`
  `--mcp-config '{"mcpServers":{}}' --agents '{}' --no-chrome --disable-slash-commands`
  `--session-id <uuid>`, then the tools:
  - brokered seats: `--tools ""` plus the brokered `--disallowedTools` list, copied from
    `_broker_claude_tui_command`;
  - direct seats: `--tools Read --allowedTools Read`, one fewer tool than the TUI's
    `Read,Write`, because nothing writes `panel-claude.txt` any more.

  It **never** emits `--bare`. The prompt goes on stdin.
- `_run_claude_print_session(command, prompt, *, env, cwd, mode, timeout_s, stall_s)` — add.
  It returns the same `(rc, text, log, tail)` shape as `_run_claude_tui_session`. Behavior:
  - Launch through the same owned-process helper the TUI uses (`launch_owned`), with
    `start_new_session=True`.
  - The env comes from `_subscription_env` (which calls `scrub_subscription_env`).
  - The working directory is the seat's scratch `out_dir`.
  - Parse stdout as one JSON event per line.
  - **Drift guard.** If the first `system/init` has `apiKeySource != "none"`, kill the process
    group and return the typed failure `claude_print_subscription_unproven`. If a
    `system/api_retry` arrives with `error` in `{authentication_failed, billing_error,
    oauth_org_not_allowed}`, kill and return `claude_print_auth_drift`. If the run reaches
    `result` with no `system/init`, also return `claude_print_subscription_unproven`.
  - **Text.** Take the `result` event's `result` field, falling back to
    `_extract_claude_stream_json_text`.
  - **Liveness.** Any parsed event counts as progress; the PTY spinner problem (agent-harness#188)
    cannot happen here. Reuse the existing stall threshold and backstop constants. If no event
    arrives within `stall_s`, return the typed failure `claude_print_stalled`.
- `_exec_claude_tui_leg` (`:9551`) — modify. After the existing deferral and auth gates, branch on
  `_panel_claude_route()`. For `print`: build with `_claude_print_seat_command`, run
  `_run_claude_print_session`, then classify the returned text through the existing
  `_classify_leg`.
  - The typed failures map to `UNAVAILABLE`, matching how `subscription_auth_unproven` is reported
    today. `claude_print_stalled` maps to `DEGRADED`, matching `claude_tui_stalled`.
  - Add `claude_route` and `claude_api_key_source` to the brokered evidence dict (around
    `:9703`). Keep every existing key.
  - Do not rename the function. Its callers and tests pin the name; Stage 2 introduces the seam.
- `_render_claude_tui_prompt` (`:6390`) — modify. Take a `route` keyword. On the print route,
  drop the "Write your review to `panel-claude.txt`" instruction. Keep the terminal-verdict
  instruction (IF-0-PNLCLAUDE-2).
- `_exec_jailed_claude_leg` (`:9990`) — **unchanged**; jailed seats stay on the TUI. Moving them
  to print, and replacing the access-token pipe with the binary reading its own
  `CLAUDE_CONFIG_DIR`, is out of scope (see Follow-ons).

### `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py` (modify)
- The brokered launch around `:451-457` — modify. Branch on `panel_invoker._panel_claude_route()`.
  On `print`, call `_claude_print_seat_command(brokered=True)` and
  `_run_claude_print_session(mode="president")`. On `tui`, run the current code unchanged.

### `phase-loop-runtime/tests/test_panel_claude_print_route.py` (create)
Tests:
- the argv golden for brokered and direct seats (no `--bare`; `--permission-prompts none`; no
  `--add-dir`; the prompt is absent from argv);
- the drift guard: `apiKeySource:"ANTHROPIC_API_KEY"` gives `claude_print_subscription_unproven`
  and the process is killed;
- `api_retry` with `billing_error` gives `claude_print_auth_drift`;
- a missing `init` fails closed;
- a happy path: `result` text with a verdict classifies `OK`;
- a stall gives `claude_print_stalled`;
- the route selector: default `print`, explicit `tui`, and an invalid value fails closed;
- the version gate: below 2.1.259 returns `UNAVAILABLE`;
- under Claude Code the seat still defers as `under_claude_code`, before the route is consulted.

All tests use a fake `claude` script that prints scripted stream-json, the same pattern as the
existing TUI fake-binary tests.

### Existing tests that pin the TUI as the only route (modify: set `PHASE_LOOP_PANEL_CLAUDE_ROUTE=tui` in the fixture; no assertion changes)
- `tests/test_panel_invoker_spawn.py` (TUI argv, `assertNotIn("-p")` at about `:81`)
- `tests/test_panel_invoker_timeout_argv.py` (the `panel-claude.txt` capture, about `:2373-2418`)
- `tests/test_advisor_board_backing_homebrew.py` (about `:158`, `:240-253`)
- `tests/test_seat_sandbox_permissions.py` (the brokered TUI golden, about `:447`; the jailed and
  sealed goldens stay as they are)
- `tests/test_panel_leg_auth_preflight_64.py`: parametrize over both routes, so "unproven auth
  never launches" holds for each.
- `tests/test_president_wiring.py` (about `:635`): pin `tui` where it asserts TUI behavior.
- The TUI liveness, trust and EOF suites (`test_panel_tui_*`, `test_review_seat_stall_1176.py`,
  `test_panel_leg_status_detail_1096.py`): pin `tui` with a module-level fixture.

## Documentation impact
- `docs/advisor-board-capabilities-card.md`: covered by Stage 1a (route env plus the new failure
  codes). Confirm that the codes landed there match the strings in this plan exactly.
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`: covered by Stage 1a.
- `docs/TEAM-ONBOARDING.md`: add one line under Claude prerequisites. Claude Code 2.1.259 or
  newer is required for the default print route, and `PHASE_LOOP_PANEL_CLAUDE_ROUTE=tui` restores
  the PTY adapter.

## Dependencies & order
1. Stage 1a is merged to `main` first.
2. In this plan: add the constants, selector and builder; then the session runner; then wire up
   `_exec_claude_tui_leg`; then the president; then pin the existing tests to `tui`; then add the
   new test file.
3. Land as a **two-parent merge**. The merge message cites Stage 1a's merge commit by full SHA
   (EC-REVIEWTRUTH-15 ancestry rule).

## Verification
```bash
cd phase-loop-runtime
uv run pytest -q tests/test_panel_claude_print_route.py
uv run pytest -q tests/test_panel_invoker_spawn.py tests/test_panel_invoker_timeout_argv.py \
  tests/test_advisor_board_backing_homebrew.py tests/test_seat_sandbox_permissions.py \
  tests/test_panel_leg_auth_preflight_64.py tests/test_president_wiring.py \
  tests/test_panel_tui_liveness_188.py tests/test_panel_tui_workspace_trust_223.py tests/test_panel_tui_eof_48.py
uv run pytest -q   # full suite; the runner's claude_print/route-selection goldens must be unchanged
# Live smoke outside Claude Code (env -u CLAUDECODE), on subscription login. Use the repo's
# existing advisor-board smoke entrypoint with a single claude seat. Expect the claude leg to be
# OK, its evidence to show claude_route=print and claude_api_key_source=none, and no TUI process.
```
Edge cases: `ANTHROPIC_API_KEY` set in the parent env (the scrub removes it, so `init` still
reports `none`); a CLI older than 2.1.259 (`UNAVAILABLE`, with no launch); a prompt larger than
1 MB (it goes on stdin, so there is no argv limit; the 10 MB stdin cap is far above panel bundle
sizes).

## Acceptance criteria
- [ ] With no route env set, a non-jailed, non-native Claude seat and the president launch
  `claude -p --output-format stream-json` with the prompt on stdin and no `--bare`. Proven by
  `test_panel_claude_print_route.py` argv goldens.
- [ ] A stream whose `system/init.apiKeySource != "none"`, or whose `api_retry.error` is an auth
  or billing category, ends the leg `UNAVAILABLE` with `claude_print_subscription_unproven` or
  `claude_print_auth_drift`, and the child process group is gone. Proven by the drift-guard tests.
- [ ] `PHASE_LOOP_PANEL_CLAUDE_ROUTE=tui` reproduces today's behavior byte-for-byte: every
  existing TUI test passes unmodified apart from the route pin.
- [ ] The full `phase-loop-runtime` suite passes, and the runner's `claude_print`
  billing/route-selection goldens are unchanged.

## Follow-ons (out of scope; file as agent-harness issues when this lands)
- **Jailed seats on print.** Drop the access-token pipe and let the unmodified binary read its own
  `CLAUDE_CONFIG_DIR`. The Claude Code legal page says developers "may not … intermediate
  Claude.ai credentials or session tokens".
- **Stage 2: a `ClaudeTransport` seam** (`tui | print | sdk`). Rename `_exec_claude_tui_leg`
  behind it.
- **Stage 3: the Agent SDK in the runner.** Use `ClaudeSDKClient` with `cli_path` pinned to the
  system `claude` (the wheel bundles its own binary and prefers it), with the env scrubbed. It
  replaces the bun `claude_channel` route and its sidecar. It needs an EC-REVIEWTRUTH-18 SDK
  amendment for any panel use, and it should reclassify the runner's `claude_print` billing
  posture from `usage_credit` (`launcher.py:750-754`).
- **`--bare` watch.** Anthropic says `--bare` will become the default for `-p`, and there is no
  opt-out flag in 2.1.293. The drift guard catches that change; add an explicit opt-out flag once
  the CLI offers one.

## Execution Policy
- execute: effort=high, reason=subprocess lifecycle + fail-closed auth guard in a 14k-line governed module
