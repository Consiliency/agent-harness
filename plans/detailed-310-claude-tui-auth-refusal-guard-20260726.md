# Detailed plan: enforce Claude TUI subscription auth and typed refusal gating

## Task

Land the independently implementable Claude portion of Consiliency/agent-harness#310.
Every Fable or Opus advisor seat must use the existing Claude Code TUI adapter with
proven first-party `claude.ai` subscription authentication. Do not add an Anthropic
API, SDK, API-key, Messages, or direct HTTP path. Do not classify refusals from
transcript text.

Scoped PMCP research is deliberately excluded and follows only after the separate
PMCP prerequisite and advisor-integration plans.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- Add a metadata-only Claude auth preflight using `claude auth status --json`.
  Accept only `loggedIn=true`, `authMethod="claude.ai"`,
  `apiProvider="firstParty"`, and a non-empty subscription type. Do not persist
  email, org ID/name, or raw probe output.
- Return `UNAVAILABLE/subscription_auth_unproven` before TUI launch when the
  eligible subscription cannot be proven.
- Centralize subscription environment scrubbing in one helper used by both
  `_subscription_env()` and `advisor_board.backing.resolve_seat_env()`; the
  model-first `invoke_board` path passes the latter explicitly and must not bypass
  the same restrictions. Remove `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_CUSTOM_HEADERS`, alternate Anthropic base-URL/provider/gateway variables,
  `CLAUDE_CODE_USE_BEDROCK`/Vertex/Foundry selectors, and configured API-key-helper
  inputs. Use run-isolated Claude settings that
  cannot select an API helper or alternate LLM gateway.
- Keep `_claude_tui_command`, self-PTY lifecycle, staged review bundle, exact
  Fable/Opus model, and TUI output ingestion as the only Claude execution path.
- Remove the `under_claude_code` native Task/subagent fulfillment bypass for
  governed/default Fable and Opus seats. If the self-PTY TUI adapter cannot run
  inside the current host, report typed `UNAVAILABLE/tui_adapter_required`; do
  not substitute a native agent that skipped subscription preflight. Retain any
  native-fill API only for explicitly non-Claude/custom seats outside this policy.
- Attach `provider_refusal_kind` and `fallback_used` as non-dataclass state with
  read-only properties, matching the existing `_needs_native_agent` pattern, so
  `dataclasses.asdict` and field-walking legacy serializers remain byte-identical.
  Accept only adapter-originated typed enum values; never infer
  them from review text, stderr, PTY tails, or verdict prose.
- Declare today's TUI adapter classifier-refusal capability unsupported. A
  refusal-looking or non-OK transcript remains preserved `DEGRADED`/`ERROR` and
  cannot trigger an Opus retry.
- Add a bounded reducer for future typed capability: only an independently
  attested authorized defensive-security request plus a genuine adapter-originated
  classifier-refusal may launch one Opus TUI retry. Attribute output to Opus,
  mark degraded/fallback-used, and fail closed on a second refusal. Keep this path
  unreachable under today's capability declaration.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/observability.py` (modify)

- Emit metadata-only auth/refusal/fallback state without raw transcript or account
  identity. Preserve existing result status semantics when new fields are absent.

### Tests (modify/add)

- `tests/test_panel_leg_auth_preflight_64.py`: cover accepted `claude.ai`/first-party
  subscription, every rejected/malformed auth shape, PII non-persistence, and
  no-launch on unproven auth.
- `tests/test_panel_invoker_spawn.py`: assert Fable and Opus still use the Claude
  TUI command; no API/SDK command or environment survives.
- Add direct legacy-leg and model-first `invoke_board` env tests proving the same
  token/base-URL/provider selectors are absent on both seams.
- `tests/test_panel_tui_liveness_188.py`: prove TUI stalls/refusal-looking tails
  remain degraded and do not trigger fallback.
- `tests/test_panel_native_fill_183.py`: prove default Fable/Opus seats are never
  deferred to native Task fill and fail unavailable when the TUI adapter cannot run.
- Add typed-refusal reducer tests: text cannot trigger, synthetic adapter type can
  select exactly one Opus TUI retry, second refusal fails closed, and non-defensive
  requests never retry.
- `tests/test_advisor_board_observability.py`: cover metadata-only emission and
  legacy byte-neutral defaults.
- Add an exact `dataclasses.asdict(PanelLegResult(...))` regression proving unset
  refusal/fallback attachments add no keys or bytes.

### Documentation and skills (modify/regenerate)

- Update advisor-board contract/capability docs and neutral skill source to state
  the TUI/subscription-only invariant and currently gated fallback.
- Regenerate harness skill bundles through the existing tooling; do not hand-edit
  generated copies.

## Dependencies and order

None. This plan may land before PMCP work.

## Execution Policy

- execute: effort=high, reason=authentication and refusal security boundary
- review: model_class=reviewer, effort=max

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest \
  tests/test_panel_leg_auth_preflight_64.py \
  tests/test_panel_invoker_spawn.py \
  tests/test_panel_tui_liveness_188.py \
  tests/test_panel_native_fill_183.py \
  tests/test_advisor_board_observability.py -q
```

`automation.suite_command`: `cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest tests/test_panel_leg_auth_preflight_64.py tests/test_panel_invoker_spawn.py tests/test_panel_tui_liveness_188.py tests/test_panel_native_fill_183.py tests/test_advisor_board_observability.py tests/test_advisor_board_backcompat.py -q`

## Acceptance criteria

- [x] Every Claude advisor seat proves `claude.ai` first-party subscription auth before launch.
- [x] API token/helper/custom-header/base-URL/gateway alternatives are scrubbed or isolated and cannot become fallback auth.
- [x] Legacy panel and model-first board paths apply the identical subscription scrub.
- [x] Fable and Opus run only through the existing Claude Code TUI adapter.
- [x] Under-Claude/default seats cannot bypass the TUI/auth preflight through native Task fill.
- [x] No Anthropic API, SDK, Messages, API-key, or direct HTTP path exists.
- [x] Transcript strings cannot create a typed refusal or trigger fallback.
- [x] Today's untyped TUI refusal/stall remains preserved and degraded without retry.
- [x] Synthetic typed capability permits at most one attributed Opus TUI retry for attested defensive work, then fails closed.
- [x] New telemetry is metadata-only and legacy results remain compatible.
