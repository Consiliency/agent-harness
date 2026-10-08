# Detailed plan: amend the frozen "never `claude -p`" premise for Claude panel seats (Stage 1a)

## Task
Stage 1a of the owner-approved graduated Claude route (TUI → `claude -p` → transport seam →
Agent SDK), chosen by the maintainer on 2026-10-08. It is the governance prerequisite for Stage 1b
(`plans/detailed-claude-print-panel-route-20261008.md`). This plan amends the frozen statements
that forbid `claude -p` for Claude panel/board/president seats. It replaces them with the property
those statements were protecting: **the seat runs on the maintainer's Claude subscription OAuth
login, never an API key, and proves that in-band.** The PTY TUI adapter stays as an opt-in
fallback route. Docs and specs only; no code.

## Research summary
The prohibition rests on a premise that no longer holds. `docs/research/model-routing-v2-integration.md:137`
says "`claude -p` is being deprecated for subscription use". That was Anthropic's June 2026 plan.
Anthropic paused it on 2026-06-15, and on 2026-10-07 its help-center article 15036540 ("Use the
Claude Agent SDK with your Claude plan") said the Agent SDK, `claude -p` and third-party apps
still draw on subscription limits. A local probe on Claude Code 2.1.293 confirms it: `claude -p
--output-format stream-json` emitted `system/init` with `apiKeySource: "none"`, which means
subscription OAuth.

The prohibition is restated in these places:
- `plans/phase-plan-v4-PNLCLAUDE.md:15` (IF-0-PNLCLAUDE-1), `:38` and `:69`.
- `specs/phase-plans-v4.md:146` and `:155`.
- `specs/phase-plans-v10.md`: `:103`, the EC-REVIEWTRUTH-16 sentence "No direct `claude -p`"
  (line 726), EC-REVIEWTRUTH-18 "no cell admits an API key, SDK, direct HTTP, gateway or
  alternate endpoint" (line 777), and the EC-REVIEWTRUTH-17 tail at `:781`.
- `docs/advisor-board-capabilities-card.md:134` ("Claude execution is TUI-only").
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md:87`, plus lines 47, 198
  and 718.
- The advisor-board skills, all four vendor variants plus the bundle copies.

Doc-drift tests that read this text:
- `test_panel_doc_contract.py`
- `test_legible_roadmap_contract.py`
- `test_skills_bundle_drift.py`
- `roadmap_assumptions.py:717-723`, which reads EC-REVIEWTRUTH-14. This plan leaves EC-14
  untouched.

## Changes

### `specs/phase-plans-v10.md` (modify)
- EC-REVIEWTRUTH-16: add a dated amendment note. Do not rewrite the goal. The note says that
  "No direct `claude -p`" is superseded for non-native Claude seats by: "a non-native Claude seat
  may run as `claude -p --output-format stream-json` only on proven subscription OAuth. That means
  a `claude auth status` preflight, `system/init.apiKeySource == "none"` asserted in-band, never
  `--bare`, and an env-scrubbed launch. Native fill under Claude Code (EC-REVIEWTRUTH-14) is
  unchanged."
- EC-REVIEWTRUTH-18: add a dated amendment note. "TUI adapter" in the title is read as "the
  subscription-proven Claude CLI adapter (print by default, TUI as an opt-in fallback)". The
  "no API key, SDK, direct HTTP, gateway or alternate endpoint" clause **stays in force for
  Stage 1**. Agent SDK admission is reserved for a later amendment (Stage 3) and is not granted
  here.
- `:103` and `:781` (EC-REVIEWTRUTH-17 tail): add an inline cross-reference to the
  EC-REVIEWTRUTH-16 amendment note. Leave the substance unchanged.

### `specs/phase-plans-v4.md` (modify)
- Lines 146 and 155: add a dated supersession note that points to the v10 EC-REVIEWTRUTH-16
  amendment.

### `plans/phase-plan-v4-PNLCLAUDE.md` (modify)
- IF-0-PNLCLAUDE-1 (line 15): add an amendment note.
  - "Never API-key auth" stays.
  - "Never `claude -p`" becomes "`claude -p` only on in-band-proven subscription OAuth, never
    `--bare`".
  - The `panel-claude.txt` scratch file becomes "the TUI route's output channel; the print route
    returns the review in the stream-json `result` event".
  - The "unsupported versions classify as `UNAVAILABLE`/`DEGRADED`" rule stays.
- IF-0-PNLCLAUDE-2: unchanged. The terminal-verdict prompt contract still binds both routes.
- Lines 38 and 69: add a supersession note with the same pointer.

### `docs/research/model-routing-v2-integration.md` (modify)
- Line 137: add a dated correction with the 2026-06-15 pause, the 2026-10-07 reaffirmation and
  the 2.1.293 probe result. Leave the original sentence in place as history.
- Line 180, open question 3: mark it resolved by Stages 1a and 1b.

### `docs/advisor-board-capabilities-card.md` (modify)
- Line 134 paragraph: change "TUI-only" to the following rule. Claude Fable/Opus seats run on the
  homebrew backing through the subscription-proven Claude CLI adapter (`PHASE_LOOP_PANEL_CLAUDE_ROUTE`
  = `print` by default, or `tui`). The "No API, SDK, Messages, direct HTTP" sentence stays.
- Keep the existing `tui_backing_required`, `tui_adapter_required` and `under_claude_code` codes
  verbatim. Add a line for the new Stage 1b codes `claude_print_subscription_unproven` and
  `claude_print_auth_drift`, so doc and code land with the same vocabulary.

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` (modify)
- Line 87 "subscription TUI only": change to "subscription CLI adapter only (print default, TUI
  fallback)".
- Lines 47, 198 and 718: add `_run_claude_print_session` next to the TUI symbols.

### Advisor-board skills (modify, through each skill's canonical source; bundle copies regenerate)
- `phase-loop-skills/advisor-board/SKILL.md` and its `_overrides/{claude,gemini,opencode}/SKILL.md`,
  plus `skills-src/{claude,codex,gemini,opencode}/*-advisor-board/SKILL.md`: apply the same
  one-sentence change from "TUI-only / self-PTY" to "subscription-proven CLI adapter".
- Regenerate `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*` with the repo's existing
  bundle sync (whatever `test_skills_bundle_drift.py` checks against). Do not hand-edit the
  bundle copies.

## Documentation impact
The whole plan is documentation. The files are listed under Changes. Untouched: the README,
`docs/TEAM-ONBOARDING.md` (neither mentions the TUI or `claude -p`) and the runner capability
matrix. The runner's `claude_print` billing posture stays `usage_credit` until Stage 3; the 1b
plan records that deferral.

## Dependencies & order
1. This plan lands first, as its own PR, and is merged to `main`.
2. Stage 1b changes a Claude panel leg's launch flags in `panel_invoker.py`, which
   EC-REVIEWTRUTH-15 treats as posture-sensitive. So 1b lands as a two-parent merge whose first
   parent already contains this amendment, and 1b's landing message cites this amendment's merge
   commit by full SHA (EC-REVIEWTRUTH-15's ancestry rule). The SHA is written at landing time,
   not in this plan.
3. The tool posture does not widen. Brokered seats keep zero tools. Direct seats go from
   Read,Write to Read only. The amendment states this, so it doubles as the EC-REVIEWTRUTH-15
   ratification record ("posture unchanged or narrowed; no execution capability added").

## Verification
```bash
cd phase-loop-runtime
uv run pytest -q tests/test_panel_doc_contract.py tests/test_legible_roadmap_contract.py tests/test_skills_bundle_drift.py
uv run pytest -q -k "roadmap_assumptions"   # EC-REVIEWTRUTH-14 atom unchanged
git grep -n "never.*claude -p\|TUI-only\|No direct .claude -p." -- specs plans docs phase-loop-skills skills-src \
  | grep -v "amend\|supersed"   # expect no unannotated hits
```

## Acceptance criteria
- [ ] Each frozen "never `claude -p`" / "TUI-only" statement listed above carries a dated
  amendment or supersession note that points to the EC-REVIEWTRUTH-16 amendment. The `git grep`
  above returns no unannotated hits.
- [ ] EC-REVIEWTRUTH-18's "no API key, SDK, direct HTTP, gateway or alternate endpoint" clause is
  still present and in force (the Agent SDK is not admitted).
- [ ] The amendment text states that no seat's tool posture widens (EC-REVIEWTRUTH-15 record).
- [ ] `test_panel_doc_contract.py`, `test_legible_roadmap_contract.py` and
  `test_skills_bundle_drift.py` pass.

## Execution Policy
- execute: effort=medium, reason=docs/spec amendment touching governed goal text and drift-tested skill copies
