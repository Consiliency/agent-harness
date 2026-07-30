# v10 governed TDD setup verification

Date: 2026-07-30

## Scope

This pre-run setup change is not one of the 13 v10 implementation phases. It prepares
the coordinator contract, fixes the doctor preflight for the fleet's real CLI names,
and repairs a Fable liveness defect found by the live setup smoke. Every v10 phase still
has to satisfy its own `EC-<ALIAS>-0` test-lane landing before production code.

## Test-first chronology

1. Doctor CLI mapping and Grok coverage:
   - Test added first: `test_executor_tool_probe_uses_runtime_cli_names_and_includes_grok`.
   - RED observed before implementation: `KeyError: 'grok'` because doctor had no Grok
     entry and still probed the logical `gemini` name.
   - GREEN after implementation: focused test passed; full doctor file reached 17 passed.
2. Golden summary consistency:
   - Test added first: `test_golden_summary_matches_tool_presence_counts`.
   - RED observed before correction: the fixture claimed `14/18`; the computed value was
     `13/18`.
   - GREEN after correction: full doctor file reached 18 passed.
3. Fable tool-only transcript activity:
   - Tests added first: `test_tool_only_transcript_growth_keeps_active_tui_leg_alive` and
     `test_transcript_activity_changes_when_tool_events_append`.
   - RED observed before implementation: both failed because
     `_latest_claude_transcript_activity` did not exist.
   - GREEN after implementation: both focused tests passed. The panel/PTy cluster then
     passed 61 tests, and board/doctor compatibility passed 70 tests.

The injection anchors are the doctor `_EXECUTORS` CLI field, the golden fixture's
computed `present` count, and `_run_claude_tui_session`'s transcript heartbeat state.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=src python -m pytest tests/test_doctor_bom.py -q
PYTHONPATH=src python -m pytest \
  tests/test_panel_tui_liveness_188.py \
  tests/test_panel_tui_workspace_trust_223.py \
  tests/test_panel_invoker_spawn.py -q
PYTHONPATH=src python -m pytest \
  tests/test_advisor_board_golden.py \
  tests/test_advisor_board_backing_homebrew.py \
  tests/test_doctor_bom.py -q
cd ..
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli \
  validate-roadmap specs/phase-plans-v10.md
git diff --check
```

Observed results: 18 passed; 61 passed; 70 passed; roadmap validation OK for 13
phases; diff check clean.

## Acceptance

- `phase-loop doctor` resolves the Gemini executor through `agy` and reports Grok.
- The v10 roadmap defaults planning to GPT-5.6 Sol at maximum effort and requires a
  full board containing Fable and Sol before phase dispatch or promotion.
- Explicit whole-phase executor assignment preserves at least three non-author vendor
  reviewers; runtime lane scheduling stays off because it resolves before phase rotation.
- Fable tool-call transcript growth keeps an active review alive without allowing
  cosmetic terminal animation to defeat genuine stall reclamation.
- A live four-seat review must deliver Fable and Sol on the exact final patch before
  this setup is considered ready.
