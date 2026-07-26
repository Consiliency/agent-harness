# Detailed plan: make Gemini 3.6 Flash high runnable in default review boards

## Task

Implement the advisor-board model portion of Consiliency/agent-harness#310:
replace Gemini 3.1 Pro Preview/display-name review seats with executable Gemini
3.6 Flash high seats, and make the model-first default review board the ratified
four-vendor set: Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5.

Preserve the legacy `invoke_panel(artifact, PANEL_LEGS)` three-leg API and its
explicit-leg behavior. This plan changes the model-first board default and review
presets deliberately; it does not add research tools or refusal fallback.

## Current-state findings

- `profiles.py` already routes Gemini implementation to `gemini-3.6-flash-high`,
  and `launcher._gemini_cli_model()` already recognizes the canonical agy ID.
- The advisor model registry contains only `Gemini 3.1 Pro`; a Flash seat is
  rejected before launch.
- `advisor_board.harness_mapping.render_gemini_model()` always appends a
  parenthetical effort word, producing an invalid double-effort form for a
  canonical ID such as `gemini-3.6-flash-high (High)`.
- The launcher and board renderer maintain separate Gemini mappings. Importing
  `launcher` from `harness_mapping` would create a cycle because `panel_invoker`
  imports both.
- `fixtures.DEFAULT_BOARD` is pinned to three seats and
  `panel_invoker.PANEL_LEGS`; `code-review` already has an availability-aware
  four-vendor composition, but uses Gemini 3.1 Pro.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/harness_mapping.py` (modify)

- Make this module the single source for agy model rendering:
  - retain the legacy display-name rendering needed for `Gemini 3.1 Pro`;
  - add the current canonical agy-ID shape and matrix alias map currently held in
    `launcher.py`;
  - expose a helper that maps `(model, effort)` to the exact agy `--model` token.
- Canonical IDs such as `gemini-3.6-flash-high` pass through unchanged when the
  requested effort matches the embedded effort.
- A base `gemini-3.6-flash` plus canonical `high` renders exactly
  `gemini-3.6-flash-high`.
- Conflicting embedded/requested effort and unknown `gemini-*` IDs fail at config
  or spec-build time. Never append a parenthetical token to a canonical ID and
  never silently coerce an unknown ID to Pro.

### `phase-loop-runtime/src/phase_loop_runtime/launcher.py` (modify)

- Remove the duplicate Gemini alias/regex implementation and import the shared
  agy renderer from `advisor_board.harness_mapping`.
- Keep `build_gemini_command()` behavior and its staged-copy review sandbox
  unchanged apart from calling the shared renderer.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/registries.py` (modify)

- Register `gemini-3.6-flash` on the Gemini lane with effort ceiling `high`.
- Retain `Gemini 3.1 Pro` only as a compatibility model for explicit user boards;
  remove it from default review composition, not from the registry.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py` (modify)

- Change the Gemini vendor seat to `gemini-3.6-flash`, effort `high`, preserving
  its distinct `alternative-approach` lens.
- Keep Fable, Sol, and Grok at their existing provider ceilings and preserve
  availability-aware backfill/distinct-lens behavior.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures.py` (modify)

- Amend the model-first `DEFAULT_BOARD` to four seats in canonical order:
  Codex/Sol, Gemini/Flash high, Claude/Fable, Grok 4.5.
- Update rendered-model and effort fixtures so Gemini expects the exact canonical
  agy ID and Grok expects its max-to-high CLI clamp.
- Preserve `CANONICAL_LEG_ORDER` and `panel_invoker.PANEL_LEGS` as the legacy
  three-leg explicit panel order; introduce a separately named four-vendor board
  order instead of redefining the frozen legacy constant.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py` (modify)

- Replace Gemini 3.1 Pro with Gemini 3.6 Flash high in review-class and general
  presets (`default`, `code-review`, `legal-review`, `legal-strategy-review`, and
  `general`).
- Also update Gemini seats in brainstorm presets unless a preset explicitly
  documents Pro-specific capability. Do not change the Claude Fable/Sonnet split
  or any lens.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)

- Change `DEFAULT_LEG_MODELS["gemini"]` to the executable
  `gemini-3.6-flash-high` token.
- Route board-seat Gemini rendering through the shared helper.
- Keep `PANEL_LEGS`, `invoke_panel` signature, availability probing, staging,
  timeout, and result semantics unchanged.

### Tests (modify)

- `tests/test_advisor_board_backcompat.py`: split the old equivalence assertion
  into (a) frozen legacy `PANEL_LEGS` compatibility and (b) the intentionally
  amended four-seat model-first default. Prove no invocation signature drift.
- `tests/test_advisor_board_golden.py`: update board-path result/order goldens to
  four seats while leaving explicit `invoke_panel(..., PANEL_LEGS)` goldens at
  three. Do not mass-rebaseline unrelated auth, timeout, or failure semantics.
- `tests/test_panel_streaming_verdicts.py`: update default-board result ordering
  to the new four-seat board while retaining three-seat expectations only for the
  explicit legacy `invoke_panel(PANEL_LEGS)` path.
- `tests/test_advisor_board_config.py`, `test_advisor_board_integration.py`, and
  `test_advisor_board_backing_homebrew.py`: cover registry validation, preset
  resolution, canonical renderer output, and one spawn per four default seats.
- `tests/test_phase_loop_launcher.py` and `test_panel_per_leg_model_66.py`: prove launcher and advisor board emit the
  same exact agy token for base and canonical Flash inputs, and fail on an unknown
  or conflicting ID.
- `tests/test_model_tier_taxonomy.py`: retain the matrix's regular Gemini model
  and ensure it is accepted by the advisor registry.

### Documentation (modify)

- Update `docs/advisor-board-capabilities-card.md` and
  `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` with the
  four-vendor default and exact Flash ID/effort semantics.
- Update `CHANGELOG.md` with the deliberate default-board amendment and legacy
  three-leg compatibility boundary.

## Dependencies and order

1. Land the shared renderer and launcher parity tests.
2. Register Flash.
3. Change composition, fixtures, presets, and `DEFAULT_LEG_MODELS` atomically.
4. Update the split legacy-vs-model-first goldens.
5. Refresh documentation.

The registry, renderer, and default swap must ship in one change; landing only
the model name recreates the observed ERROR seat.

## Execution Policy

- execute: effort=high, reason=adapter ID normalization plus deliberate golden amendment
- review: model_class=reviewer, effort=max

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest \
  tests/test_advisor_board_backcompat.py \
  tests/test_advisor_board_golden.py \
  tests/test_advisor_board_config.py \
  tests/test_advisor_board_integration.py \
  tests/test_advisor_board_backing_homebrew.py \
  tests/test_panel_streaming_verdicts.py \
  tests/test_phase_loop_launcher.py \
  tests/test_panel_per_leg_model_66.py \
  tests/test_model_tier_taxonomy.py -q
PYTHONPATH=src python -c "from phase_loop_runtime.advisor_board.harness_mapping import render_seat_invocation; assert render_seat_invocation('gemini','gemini-3.6-flash','high').model == 'gemini-3.6-flash-high'"
```

`automation.suite_command`: `cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest tests/test_advisor_board_backcompat.py tests/test_advisor_board_golden.py tests/test_advisor_board_config.py tests/test_advisor_board_integration.py tests/test_advisor_board_backing_homebrew.py tests/test_panel_streaming_verdicts.py tests/test_phase_loop_launcher.py tests/test_panel_per_leg_model_66.py tests/test_model_tier_taxonomy.py -q`

## Acceptance criteria

- [ ] `gemini-3.6-flash` is registered on the Gemini lane with ceiling high.
- [ ] Base and canonical Flash forms render exactly to `gemini-3.6-flash-high`; no parenthetical or double-effort artifact is possible.
- [ ] Unknown or effort-conflicting `gemini-*` IDs fail loudly.
- [ ] The model-first default review board contains Fable 5, Sol, Gemini 3.6 Flash high, and Grok 4.5 with distinct lenses.
- [ ] Review/general presets no longer default to Gemini 3.1 Pro Preview.
- [ ] Legacy `PANEL_LEGS == ("codex", "gemini", "claude")` and explicit `invoke_panel` behavior remain compatible.
- [ ] Launcher and advisor-board paths share one Gemini rendering implementation.
- [ ] No default or fixture names the nonexistent Grok 5.5 model.
