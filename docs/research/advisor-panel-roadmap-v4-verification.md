# Advisor-Panel Roadmap v4 Verification

Date: 2026-06-30

This document is the metadata-only closeout evidence for
`specs/phase-plans-v4.md`.

## Runtime And Skill Verification

- Focused panel/launcher/routing/skill slice:
  `PYTHONPATH=src python -m pytest tests/test_panel_invoker.py tests/test_panel_invoker_spawn.py tests/test_governed_gate_crfixes.py tests/test_governed_review.py tests/test_skills_canon_parity.py tests/test_skills_bundle_drift.py tests/test_model_class_policy.py tests/test_route_log.py tests/test_phase_loop_launcher.py -q`
  passed with 80 tests, 52 skipped, and 299 subtests.
- Full runtime suite:
  `PYTHONPATH=src python -m pytest -q`
  passed with 1282 tests, 625 skipped, and 458 subtests.
- Roadmap validation:
  `PYTHONPATH=phase-loop-runtime/src python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v4.md`
  passed for 6 phases.
- Manifest validation:
  `python -m json.tool plans/manifest.json`
  passed.
- Agent-harness diff check:
  `git diff --check`
  passed.

## Inline Artifact Evidence

Structured smoke evidence is in
`phase-loop-runtime/tests/test_panel_invoker_spawn.py`:

- `test_codex_command_prompt_contains_inline_artifact_and_closes_stdin` proves the
  Codex leg receives the sentinel artifact in the command prompt path and uses
  `stdin=subprocess.DEVNULL`.
- `test_gemini_command_prompt_contains_inline_artifact_without_add_dir_and_closes_stdin`
  proves the Gemini leg receives the sentinel artifact in the command prompt path,
  does not depend on `--add-dir`, and uses `stdin=subprocess.DEVNULL`.
- `test_claude_leg_uses_agent_view_sonnet5_and_inline_prompt` proves the Claude
  leg uses Agent View with `claude-sonnet-5`, receives the inline artifact, strips
  API-key env values, and avoids `claude -p`.

No live model-output transcript was recorded in this closeout; the proof is
structured command-construction/status evidence from the runtime tests.

Metadata-only liveness observed all three CLI legs on PATH:
`available_panel_legs=codex,gemini,claude`.

## Dotfiles Cutover Evidence

Dotfiles redaction was executed in
`/mnt/workspace/worktrees/dotfiles-advisor-panel-redact-20260630` on branch
`codex/advisor-panel-redact-20260630`.

Checks passed:

- `bash -n bootstrap.sh`
- `git diff --check`
- `test ! -e shared/skills/advisor-panel/scripts/run_cli_panels.sh`
- `test ! -e shared/skills/advisor-panel/scripts/run_claude_leg.sh`
- `test ! -e shared/skills/advisor-panel/references/capability-matrix.md`
- inverted `rg -n "run_cli_panels|run_claude_leg" shared/skills/advisor-panel`
  returned no matches.

The remaining dotfiles advisor-panel path is
`shared/skills/advisor-panel/SKILL.md`, a compatibility shim pointing to the
agent-harness runtime and harness-prefixed advisor-panel skills.

## Issue Closeout Notes

Issue #36 can be updated with:

- Agent-harness owns `phase_loop_runtime.panel_invoker`.
- Panel statuses and timeout policy are frozen and tested.
- Codex and Gemini receive inline review artifacts through command input.
- Claude uses local Claude Code Agent View with `claude-sonnet-5` and a
  `2.1.197` minimum-version gate.
- Full runtime suite passed.

Issue #135 can be updated with:

- Dotfiles no longer carries standalone advisor-panel scripts or reference
  implementation files.
- The unprefixed dotfiles `advisor-panel` skill is compatibility guidance only.
- Bootstrap continues to install phase-loop workflow skills from the pinned
  agent-harness clone.
- Redaction checks and the agent-harness inline-artifact smoke tests passed.

No secrets, local auth payloads, provider transcripts, or environment values are
included in this evidence.
