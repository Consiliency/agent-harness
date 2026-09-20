# Detailed plan: native-first claude seat under Claude Code, machine-decided, counted by governed loops (agent-harness#396, agent-harness#636)

- status: proposed
- refs: Consiliency/agent-harness#396, Consiliency/agent-harness#636, Consiliency/agent-harness#906 (the train-review consumer), Consiliency/agent-harness#914 (landed gate this extends)
- execute: effort=high, reason=review-seat routing touches the HARDEN launch boundary and a floor that gates merges

## Task

The maintainer's standing ruling (recorded on agent-harness#396 and #636, restated 2026-09-20): a harness
fills its native models' seats through its own native sub-agent capability; TUI/CLI adapters serve only
non-native hosts. Under Claude Code the claude seat must therefore be filled by the driving session's native
sub-agent and COUNT toward the reviewer floor. Today the runtime encodes the inversion in three coordinated
places, so every in-session board and the new train review run 3 of 4 seats with the claude seat reported as
`UNAVAILABLE/tui_adapter_required` and no fill request:

1. `panel_invoker.native_agent_leg_request` raises for TUI-policy models (`claude-fable-*`, `claude-opus-*`),
   which are the ONLY default claude seat models, so the deferred seat never carries a `NativeAgentLegRequest`
   (`invoke_board` skips `attach_native_agent_request` when `_claude_tui_policy_model(seat.model)`).
2. `_exec_claude_tui_leg` defers under Claude Code with the typed detail `tui_adapter_required`, whose prose
   asserts the opposite route.
3. The claude skill prose (`claude-advisor-board/SKILL.md` around lines 115 and 139) says "Never fill the
   seat with a native Task Agent" and "expect … no native-fill request".

And even where a request IS surfaced (non-TUI-policy models, `advisor-board --json`), nothing lets the
driving session's fill be handed BACK so it counts: `PanelResult.usable_legs` sees only runtime-spawned
legs, and `run_governed_premerge_loop` / `governed_board_gate` / `run_train --review-only` have no input
for a supplied leg. The seat is fillable in prose only (agent-harness#636's complaint).

Non-native hosts (codex, gemini, opencode) keep the self-PTY TUI adapter route unchanged.

## Research summary

- `panel_invoker.py`: `_under_claude_code` (CLAUDECODE=1 / CLAUDE_CODE_ENTRYPOINT), `_claude_leg_deferred_reason`
  (`under_claude_code` vs `native_adapter_required`), `NativeAgentLegRequest` + `native_agent_leg_request`
  (pure builder; raises for TUI-policy models), `attach_native_agent_request` / `PanelLegResult.needs_native_agent`
  / `PanelResult.native_fill_requests` (ABDNATIVE #183 companion, live caller in `invoke_board`),
  `_TYPED_UNAVAILABLE_DETAILS` (`subscription_auth_unproven`, `tui_adapter_required`, `tui_backing_required`),
  `_exec_claude_tui_leg` (defers under Claude Code), the HARDEN review-mode gate (`native_host_deferral_only`,
  `exact_broker_routes`, factory + revalidation) which is reached BEFORE any deferral result is built.
- `cli.py`: `_native_agent_request_json` and the `advisor-board --json` payload's `needs_native_agent`.
- `governed_review.governed_board_gate` (agent-harness#914) and `governed_premerge.run_governed_premerge_loop`
  (forwards a fixed kwarg set to `invoke`); `train_runner.run_train(review_only=True)`; `_default_train_review`.
- `roadmap_assumptions.py` reads `seat_result == "UNAVAILABLE/tui_adapter_required"` (a consumer of the token).
- The train bundle and an `advisor-board` artifact are deterministic BEFORE any seat is spent, so a fill can be
  produced first and supplied to a single invocation: no re-spend, no leg caching, no in-run mailbox.

## Decisions for the board

- **D1 Routing (fixes the inversion).** Under Claude Code the claude seat — every claude model, TUI-policy
  included — defers with typed detail `under_claude_code` AND carries a `NativeAgentLegRequest`.
  `native_agent_leg_request` raises for TUI-policy models only when NOT under Claude Code (there the adapter is
  the route). `under_claude_code` joins `_TYPED_UNAVAILABLE_DETAILS`; `tui_adapter_required` is no longer emitted
  under Claude Code (it remains the token for a host where the adapter genuinely cannot run). The HARDEN
  review-mode gate, factory and revalidation are untouched and still run before the deferral is built.
- **D2 Supplied fill (makes it count).** A frozen `NativeLegFill(seat_key, leg="claude", model, text,
  artifact_sha256, brief_sha256, filled_by, filled_at)` supplied to `invoke_board(native_leg_fills=…)`. For a
  seat deferred under Claude Code whose fill matches the staged artifact digest AND the effective brief digest,
  the leg result is built from the fill: status from the terminal-verdict contract (OK if conforming, else
  DEGRADED), `text` = fill text, `detail="native_fill"`, provenance attached as metadata (never a schema field).
  A supplied fill whose digests do not match, or for a seat that was not deferred, is a typed refusal
  (`native_fill_digest_mismatch` / `native_fill_seat_not_deferred`) — never silently ignored, never a spawn,
  never authority. `usable_legs` then counts the seat.
- **D3 Emit-then-fill protocol (machine-decided, agent-harness#636).** `advisor-board --emit-native-request`
  and `run-train --governed --review-only --emit-native-request` compose the board, stage the exact artifact,
  and write `<out>/native-fill/request.json` (the `NativeAgentLegRequest` + `artifact_sha256` + `brief_sha256`
  + the staged artifact path) WITHOUT spending any seat; the driving session runs its native sub-agent with the
  request's instructions and writes `<out>/native-fill/claude.md`; the same command with
  `--native-leg claude=<file>` runs the other seats and counts the fill (D2). `governed_board_gate` and
  `run_governed_premerge_loop` forward `native_leg_fills`. Alternative considered and rejected: an in-run
  mailbox the runtime polls while other seats run — it couples the HARDEN leg lifetime to the driving session's
  reaction time and needs a background launch plus a watcher; the two-phase protocol has no timing.
- **D4 Prose in lockstep.** The four claude-* advisor/board/run-train skills state the native-fill protocol;
  the non-native skills (codex/gemini/opencode) are NOT changed (their route is the adapter).
  `roadmap_assumptions` recognises `under_claude_code` where it recognised `tui_adapter_required`.
- **D5 Non-native hosts unchanged.** `_exec_claude_tui_leg` outside Claude Code, `native_adapter_required`,
  the self-PTY trust gate, subscription scrubbing: byte-neutral. No `claude -p`, no SDK, no API key route
  (the fill is DATA from the first-party session, not a launch).

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `native_agent_leg_request` — modify — raise for TUI-policy models only when `not _under_claude_code(env)`.
- `_exec_claude_tui_leg` — modify — under Claude Code return `("UNAVAILABLE", "under_claude_code")`.
- `_TYPED_UNAVAILABLE_DETAILS` — modify — add `under_claude_code`.
- `invoke_board` per-seat matrix — modify — attach the native request for the claude seat under Claude Code
  regardless of TUI policy; accept `native_leg_fills`; apply D2 after the HARDEN gate, before `PanelResult`.
- `NativeLegFill` (frozen dataclass) + `load_native_leg_fill(path)` + `attach_native_fill_provenance` — add.
- `native_fill_request_payload(board, artifact, brief_ref, …)` — add — the emit-side dict (D3), pure.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `advisor-board` — modify — `--emit-native-request` and repeatable `--native-leg <seat>=<file>`.
- `run-train` — modify — same two flags, valid only with `--governed --review-only`.

### `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `governed_premerge.py`, `train_runner.py` (modify)
- `governed_board_gate(native_leg_fills=None)` — modify — forward to `invoke_board`.
- `run_governed_premerge_loop(native_leg_fills=None)` — modify — forward on the `invoke` seam only when set.
- `run_train(review_only, emit_native_request, native_leg_fills)` — modify — emit arm returns
  `{"status": "native_fill_requested", "request_path", "artifact_path"}` before any board; fills forwarded.

### `phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py` (modify)
- the `tui_adapter_required` seat-result check — modify — also recognise `under_claude_code`.

### `phase-loop-runtime/tests/test_native_claude_seat_fill.py` (create)
- routing under Claude Code for fable/opus seats (request attached, detail `under_claude_code`); outside
  Claude Code unchanged (adapter route, `native_adapter_required` builder unchanged); D2 acceptance (counts,
  4/4 usable, floor honoured); digest mismatch refused; fill for a non-deferred seat refused; no spawn and no
  authority constructed for a fill; emit arm spends no seat (spawn = never-called sentinel); `run-train`
  emit → fill → invoke end to end with the #914 gate; CLI flag validation.

## Documentation impact
- `skills-src/claude/claude-advisor-board/SKILL.md` — modify — replace the two inversion paragraphs with the
  emit → native sub-agent → `--native-leg` protocol; regenerate `phase-loop-skills/` and `skills_bundle/`.
- `skills-src/claude/claude-run-train/SKILL.md` — modify — the review-only protocol under Claude Code.
- `CHANGELOG.md` — modify — Unreleased entry naming agent-harness#396/#636.
- `docs/advisor-board-capabilities-card.md` — modify — the Claude Code row.

## Dependencies & order
1. D1 + D2 + tests in `panel_invoker` (PR-1, with the `advisor-board` CLI flags and the claude skill prose).
2. D3 train/gate/loop forwarding + `run-train` flags + run-train skill (PR-2), on top of PR-1.
Two PRs keep each under the review size that converged on agent-harness#914.

## Verification
```
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python -m pytest -q \
  phase-loop-runtime/tests/test_native_claude_seat_fill.py phase-loop-runtime/tests/test_panel_invoker*.py \
  phase-loop-runtime/tests/test_advisor_board*.py phase-loop-runtime/tests/test_governed_*.py \
  phase-loop-runtime/tests/test_train_*.py phase-loop-runtime/tests/test_roadmap_assumptions*.py
# live, under Claude Code, from a git toplevel: emit → fill natively → invoke; expect 4 usable legs
phase-loop advisor-board --board code-review --artifact <bundle> --emit-native-request --json
phase-loop advisor-board --board code-review --artifact <bundle> --native-leg claude=<fill> --json
```
Mutants that must fail: request no longer attached for a fable seat; digest check removed; fill accepted for
a non-deferred seat; emit arm spawns; outside-Claude-Code route changed.

## Acceptance criteria
- [ ] Under Claude Code, `invoke_board(CODE_REVIEW_BOARD, …)` returns the claude seat `UNAVAILABLE/under_claude_code` with `needs_native_agent` set, for the default (fable) seat.
- [ ] A supplied fill with matching artifact and brief digests makes the seat usable and the board 4 of 4; a mismatched digest or a non-deferred seat is a typed refusal.
- [ ] `run-train --governed --review-only --emit-native-request` spends no seat and writes the request; with `--native-leg claude=<file>` the approval record's `usable_reviewers` counts the fill.
- [ ] Outside Claude Code every existing panel/board test is byte-identical in outcome; `native_agent_leg_request(env=<non-Claude>)` still raises for TUI-policy models.
- [ ] The four claude-* skills describe the protocol; codex/gemini/opencode skill prose is unchanged.
