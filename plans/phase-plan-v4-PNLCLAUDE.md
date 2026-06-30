---
phase_loop_plan_version: 1
phase: PNLCLAUDE
roadmap: specs/phase-plans-v4.md
roadmap_sha256: 906d5d558f4b713abeda01b9c1e443ab09bf9d7203cee49777d7a92fde2f4261
---

# PNLCLAUDE: Repo-Grounded Claude Leg And Whole-Feature Review

## Context

Phase `PNLCLAUDE` follows the completed `PNLFEED` inline-artifact contract. Codex and Gemini panel legs already receive review material in their prompt input path; the remaining panel runtime gap is the Claude leg, which is still hard-coded as `UNAVAILABLE`. This phase adds a local Claude Code Agent View path guarded by the Sonnet 5 Claude Code version requirement and keeps unsupported or unauthenticated Claude states fail-closed.

## Interface Freeze Gates
- [ ] IF-0-PNLCLAUDE-1 — Claude panel execution contract: Claude leg uses local Claude Code Agent View (`claude --bg`) with `claude-sonnet-5`, never API-key auth or `claude -p`, and unsupported Claude Code versions classify as `UNAVAILABLE` or `DEGRADED`.
- [ ] IF-0-PNLCLAUDE-2 — Whole-feature panel prompt contract: panel prompts ask for repo-grounded, integration-oriented review of the whole feature and still require a terminal `AGREE`, `PARTIALLY AGREE`, or `DISAGREE` verdict.

## Lane Index & Dependencies

SL-0 — Claude Agent View leg integrator
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no
SL-1 — Claude contract note and phase verification reducer
  Depends on: SL-0
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Claude Agent View Leg Integrator
- **Scope**: Replace the hard-coded Claude-unavailable panel leg with a version-gated local Claude Code Agent View execution path.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`
- **Interfaces provided**: `IF-0-PNLCLAUDE-1`, `_claude_code_version_tuple`, `_claude_code_support_status`, `_exec_claude_agent_view_leg`
- **Interfaces consumed**: `(pre-existing)` `IF-0-PNLFEED-3`, `(pre-existing)` `CLAUDE_IMPLEMENTER_MODEL`, `(pre-existing)` `ClaudeAgentViewAdapter`, `(pre-existing)` `_render_leg_prompt`, `(pre-existing)` `_classify_leg`, `(pre-existing)` `terminal_verdict`
- **Parallel-safe**: no
- **Tasks**:
  - test: Add subprocess-stubbed tests proving Claude uses `claude-sonnet-5` through `claude --bg`, closes stdin, strips API-key env vars, and never invokes `claude -p`.
  - test: Add version-gate tests proving missing, unparsable, or below-`2.1.197` Claude Code returns `UNAVAILABLE` or `DEGRADED` without silently selecting older Sonnet behavior.
  - test: Add Agent View lifecycle tests proving terminal verdict logs classify as `OK`, terminal failed states classify fail-closed, and timeouts include configured timeout metadata without leaking artifact text.
  - impl: Add the Claude Code version parser/support gate and Agent View command/polling path in `panel_invoker.py`.
  - impl: Route Claude prompt rendering through the same inline artifact and whole-feature review instructions as other panel legs.
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_panel_invoker_spawn.py -q`

### SL-1 — Claude Contract Note And Phase Verification Reducer
- **Scope**: Record the Claude Agent View contract and run the focused panel verification slice.
- **Owned files**: `docs/research/model-routing-v2-integration.md`
- **Interfaces provided**: phase evidence for `IF-0-PNLCLAUDE-1` and `IF-0-PNLCLAUDE-2`
- **Interfaces consumed**: `IF-0-PNLCLAUDE-1`, `IF-0-PNLCLAUDE-2`
- **Parallel-safe**: no
- **Tasks**:
  - impl: Add a short PNLCLAUDE amendment documenting the `claude-sonnet-5` Agent View path, version gate, and fail-closed fallback behavior.
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_panel_invoker.py tests/test_panel_invoker_spawn.py tests/test_governed_gate_crfixes.py tests/test_governed_review.py -q`
  - verify: `python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v4.md`

## Dispatch Hints
- preferred executors: `codex`
- allowed executors: `codex`
- fallback executors: `codex`
- required capabilities: `structured_output`

## Execution Policy
- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- execute: executor=`codex`, model=`gpt-5.5`, effort=`high`, work-unit=`lane_execute`, reason=`Claude Agent View integration touches panel runtime behavior`
- SL-1: executor=`codex`, model=`gpt-5.5`, effort=`medium`, work-unit=`phase_reducer`, reason=`docs and verification reducer`

## Execution Notes

- Do not use `claude -p`; the supported local Claude path is Claude Code Agent View via `claude --bg`.
- Do not introduce Anthropic API-key execution. Child environments must continue stripping provider API key variables.
- Claude Code versions below `2.1.197`, missing `claude`, or malformed version output should degrade the Claude leg and preserve the Codex/Gemini panel result.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_panel_invoker_spawn.py`, `docs/research/model-routing-v2-integration.md`
- evidence paths: `plans/phase-plan-v4-PNLCLAUDE.md`, `specs/phase-plans-v4.md`, focused pytest output
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

```bash
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_panel_invoker_spawn.py -q
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_panel_invoker.py tests/test_panel_invoker_spawn.py tests/test_governed_gate_crfixes.py tests/test_governed_review.py -q
PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v4.md
```

## Acceptance Criteria
- [ ] Claude leg routes Sonnet-family panel execution to `claude-sonnet-5`.
- [ ] Claude Code version below `2.1.197`, missing CLI, or malformed version output records `UNAVAILABLE` or `DEGRADED`, not a silent fallback.
- [ ] `phase-loop-runtime/tests/test_panel_invoker_spawn.py` proves the Claude leg is no longer hard-coded unavailable when the supported Agent View path is available.
- [ ] `phase-loop-runtime/tests/test_panel_invoker_spawn.py` proves author/reviewer boundary remains visible and the panel can degrade when Claude is unavailable.
- [ ] `phase-loop-runtime/tests/test_panel_invoker_spawn.py` proves review prompts request repo-grounded, whole-feature, integration-oriented findings and keep the terminal verdict contract.
- [ ] No implementation requires API-key auth or unsupported headless `claude -p` behavior.
