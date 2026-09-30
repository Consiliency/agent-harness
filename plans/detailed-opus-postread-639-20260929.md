---
title: Diagnose and repair subscription TUI post-read silence
status: executing
execution_ready: true
automation:
  suite_command: "uv --directory phase-loop-runtime run --locked --group test pytest tests/ -m 'not dotfiles_integration' -q"
---

# Detailed execution plan: agent-harness#639

## Task

Owner authorized isolated Agent Harness diagnosis/repair and routine follow-
through without more approval prompts. Restore usable required Opus review for
the verified Talk-to-Tux worker candidate, without changing its running app,
KVM, audio, inference endpoints, reviewer model/effort or approval requirements.

## Research summary

Fresh upstream main is the input b6a482faf7177ce5082267d584a689b2b7c95607.
`panel_invoker._run_claude_tui_session` reclaims after 180 seconds without
observable reviewer progress. The last exact Talk-to-Tux session completed eight
Reads, then produced no assistant event before reclaim. Open agent-harness#639
already records failed restart/nudge recovery and proposes request-lifecycle
evidence first. The installed Claude CLI supports `--debug-file`; first-party
subscription auth preflight passed. No direct API, gateway or print-mode route.

## Changes

1. Own `.dev-skills/verification/opus-postread-639-20260929/**` only for isolated
   scripts, private CLI traces and reduced receipts. Create private trace folders
   mode 0700, raw trace files mode 0600; never publish or print raw trace, auth,
   requests, headers or provider payloads. Retain only allowlisted lifecycle
   event categories/counts/timings and completed-read metadata.
   Runner receipts are also owned under
   `phase-loop-runtime/.dev-skills/verification/opus-postread-639-20260929/**`.
   Run verification with the runtime package as its repo root, not the monorepo
   root whose unrelated Dagger package has a different Python floor.
2. Run one exact current Talk-to-Tux pointer-request diagnostic using the fresh
   source self-PTY adapter, pinned Opus 5.5/max, Read-only tools and a unique
   exact-session transcript. No blind retry/nudge. Trace only this owned session.
   Observed baseline: six completed Reads, then a CLI first-chunk event after
   the final Read, but no later assistant event before the 180-second cutoff.
   Claude Code 2.1.285 is already the current upstream release. Run one
   controlled same-input observation with a 600-second silence limit and
   900-second hard backstop to distinguish premature reclaim from prolonged
   stream silence. This is a diagnostic-only caller override, not a production
   timeout change or acceptance based on process activity. No nudges or retries
   after that control. Record actual elapsed time and terminal outcome.
3. Repair only the measured cause in
   `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (existing TUI
   startup/liveness/diagnostic entities), with regression coverage in
   `phase-loop-runtime/tests/test_panel_tui_liveness_188.py` and, if necessary,
   `test_panel_claude_review_output.py`. Amend this section with the exact
   repair before source edits; do not guess from animation or process presence.
   Measured diagnostic gap: `claude_tui_stalled` records process/time metadata
   but cannot distinguish an unread prompt, pending tools, or silence after
   completed tools. Add content-free counts and whether a later assistant event
   exists, using only the caller-bound exact transcript. Keep the same typed
   status, kill clock, output authority and default timeout. Missing/unreadable
   transcripts remain explicitly unknown; never search neighboring sessions.
   This is an observability repair, not a claimed provider-stall cure. Regress
   matched/unmatched tools, malformed input, missing exact binding, and no false
   heartbeat/approval from completed Reads.
4. Update this plan and `plans/opus-postread-639-diagnostic-20260929.md`.
   Preserve existing status vocabulary
   and subscription/permission/isolation contracts. If typed detail must change,
   inspect its declarations and tests before amending the owned paths.
5. Verify narrow regressions then the runner-owned full runtime suite. Use a
   private test environment; do not replace the installed runtime before it
   passes. Retain the controlled substantive review, which has now completed
   AGREE against the unchanged Talk-to-Tux source freeze; reconcile its actual
   verdict rather than repeat an expensive successful review. That session
   loaded fresh-main adapter code before the diagnostic-only failure-tail edit;
   the success/output-authority path is unchanged and separately regressed.
   Independently review the narrow Harness diagnostic delta with a manually
   launched read-only Sol CLI using these source/test/plan pointers and no
   private traces or source bundle. This review is not an Opus substitute.
   The first full runtime run reached 72% with two failure markers before its
   1200s wall-clock limit. Preserve its `nonzero_exit` artifact. One diagnostic
   `-x -vv --tb=short` run with a 2400s bound may localize the first failure;
   it is not a replacement green full-suite receipt. Repair only owned causes
   or install a missing test requirement; outside-plan failures stay blockers.
   Owner subsequently authorized necessary verification repairs. The localized
   first failure is the optional exact historical dotfiles snapshot selecting a
   shared checkout whose `branch.main.vscode-merge-base` config name is rejected
   by the existing production authority guard. Do not change that checkout or
   weaken the guard/test. Prepare a clean, non-shared clone of the committed
   dotfiles and its pinned public submodule under the owned private evidence
   prefix, and use the existing `PHASE_LOOP_TEST_DOTFILES_REPO` test seam. No
   private/untracked dotfiles content or config values are copied or published.
   Independently localize the CONFORM history test failure; restore genuinely
   required Git objects by read-only fetch if missing, without changing input
   HEAD, test assertions, or the frozen source. Amend exact owned source paths
   before any further source repair. Preserve all failed receipts and rerun the
   original full inventory with an adequate bounded wall-clock budget.
   The CONFORM failure is now confirmed at its clean-candidate assertion; all
   three required history objects are present. Make a local verification
   checkpoint commit containing only this plan, the reduced diagnostic report,
   and the reviewed source/test delta. This is not publication or a release;
   it provides real clean Git identity for the existing provenance test, rather
   than mocking cleanliness or weakening the assertion. Keep private runner
   evidence excluded. Run the original inventory on that committed candidate
   with the isolated fixture and a 3600s bound, preserving earlier failures.
   Reconcile the completed Opus review in the existing owned Talk-to-Tux tree:
   `plans/detailed-baml-language-migration-probe-20260928-0605.md`,
   `plans/baml-language/parity.json`, and
   `.dev-skills/verification/baml-worker-20260929/report.md` plus a new owned
   `reviews/round6/opus-completed/**` receipt prefix beneath that evidence root.
   Never overwrite the previous missing verdict or relabel original failures.

## Documentation impact

Plan and reduced report initially; add operator documentation only for a
measured user-visible change. No generated bundles, governance contracts,
settings, credentials or other agents' worktrees are edited. No public raw data.

## Verification

- Fresh first-party subscription/CLI-help metadata preflight.
- Exact-input diagnostic receipt names dispatch/stream/first-event/error facts
  only when observed; unobserved facts remain unknown, not provider attribution.
- `uv sync --locked --group test` in `phase-loop-runtime`.
- `uv run --locked --group test pytest tests/test_panel_tui_liveness_188.py
  tests/test_panel_claude_review_output.py tests/test_panel_tui_eof_48.py
  tests/test_panel_tui_workspace_trust_223.py -q`.
- `uv run --locked --group test pytest tests/ -m 'not dotfiles_integration' -q`.
- `git diff --check`; complete runner artifact and source hash binding.
- Real substantive Opus self-PTY review: actual required-file reads, completed
  terminal verdict and adapter-owned cleanup, never a tiny health prompt proxy.

## Acceptance criteria

- Diagnosis distinguishes observed request lifecycle from missing assistant
  transcript, with no raw/private data disclosure (diagnostic reduced receipt).
- Measured repair preserves fail-closed output authority, model, permissions,
  isolation, genuine-progress and cleanup semantics (named regression tests).
- Targeted and full runtime verification pass in the owned tree (runner receipt).
- Substantive Talk-to-Tux Opus review returns a usable verdict bound to unchanged
  source (exact session/read/verdict receipts). A blocker is reconciled, not waived.
- No Talk-to-Tux runtime/KVM/inference change, no unrelated git changes or raw
  trace publication (dirty-path audit and operational metadata).
