# Detailed plan: native-first claude seat under Claude Code, machine-decided, counted by governed loops (agent-harness#396, agent-harness#636)

- status: proposed (r2 — amended after board round 1: gemini AGREE, codex DISAGREE, claude PARTIALLY AGREE, grok PARTIALLY AGREE)
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
  under Claude Code (it remains the token for a host where the adapter genuinely cannot run). Both deferral
  paths change (r2, gemini C / codex C): the per-seat matrix AND the early `native_host_deferral_only and spawn
  is None` return in `invoke_board`, which today independently emits `tui_adapter_required` and skips the
  request for TUI-policy models; `tui_backing_required` stays a refusal on both paths. The HARDEN review-mode
  gate, factory and revalidation are untouched and still run before either deferral result is built.
  Consumer with semantics (r2, claude 8 overrides the first draft): `roadmap_assumptions.
  _classify_reviewtruth_transition` is the LEGIBLE roadmap's live probe for THIS transition
  (`legible_evidence._observe_reviewtruth_fable_transition` captures the observation) — `pending` requires
  `seat_result == "UNAVAILABLE/tui_adapter_required"` with `native_fill_request is False`; `resolved`
  requires the issue CLOSED with `native_fill_request is True`, `verdict_bound is True`, `seat_count ==
  "FULL"`. The probe is the instrument this fix is graded by, so it is NOT loosened: neither arm changes.
  Instead the transition is sequenced so the probe never observes a mixed state — the routing flip (token +
  request attach on both paths) lands in the SAME PR that closes agent-harness#396 and #636, after which the
  `resolved` arm is what a live observation satisfies. Tests pinning the old token
  (`test_panel_native_fill_183.py` — which today calls the inversion "load-bearing SECURITY" at ~:386-394 —
  `test_legible_roadmap_contract.py`, `test_legible_review_repairs.py`, `test_legible_evidence.py`,
  `test_govlean_roadmap_reseal.py`, `test_panel_invoker_spawn.py`) are updated for the Claude Code case only;
  non-native expectations unchanged. Below-minimum support (claude, non-blocking): the claude-only-board
  `_claude_code_support_status` branch in `invoke_board` returns `UNAVAILABLE` with the support detail and
  no request — under Claude Code that is a genuine "no claude here", left as is, but it must NOT be
  confused with a deferral: the fill ingestion refuses it (`native_fill_seat_not_deferred`).
- **D2 Supplied fill (makes it count).** A frozen `NativeLegFill(seat_key, leg="claude", model, text,
  artifact_sha256, brief_sha256, filled_by, filled_at)` supplied to `invoke_board(native_leg_fills=…)`. For a
  seat deferred under Claude Code whose fill matches the staged artifact digest AND the effective brief digest,
  the leg result is built from the fill: status from the terminal-verdict contract (OK if conforming, else
  DEGRADED), `text` = fill text, `detail="native_fill"`, provenance attached as metadata (never a schema field).
  Fill ingestion contract (r2, codex A/E, gemini E, grok A): the fill is applied ONLY to a seat whose runtime
  result is `UNAVAILABLE` with detail exactly `under_claude_code` AND carries `needs_native_agent` (an empty `UNAVAILABLE` from `tui_backing_required`
  or an authentication refusal is NOT fillable); `seat_key` AND `model` must match the emitted request; a
  second fill for the same seat, or a fill for a seat that produced a runtime result, is refused
  (`native_fill_duplicate_seat` / `native_fill_seat_not_deferred`) — a fill never replaces a runtime leg and
  each seat counts once; digest mismatch is `native_fill_digest_mismatch`. Status is derived from the
  terminal-verdict contract: OK only when the LAST non-empty line is a conforming verdict, else DEGRADED
  (a fill without a verdict never counts as usable). All refusals are typed, never silent, never a spawn,
  never authority. Application point (r2, claude 4): fills are applied to the collected leg results
  IMMEDIATELY after every seat has returned and BEFORE `president_findings_from_legs` / `invoke_president`
  and before `PanelResult` is assembled, on both deferral paths — the president rules on the same legs
  `usable_legs` counts; a fill can never leave "3 ruled on, 4 usable". Fabrication limit stated out loud
  (claude 5): the binding defeats SUBSTITUTION (another bundle, another brief, a seat the runtime ran, a seat
  dropped by author exclusion) but does not prove a model produced the text; provenance is a first-party
  assertion recorded as metadata, not cryptographic evidence. `usable_legs` then counts the seat.
- **D3 Emit-then-fill protocol (machine-decided, agent-harness#636).** `advisor-board --emit-native-request`
  and `run-train --governed --review-only --emit-native-request` compose the board, stage the exact artifact,
  and write `<out>/native-fill/request.json` (the `NativeAgentLegRequest` + `artifact_sha256` + `brief_sha256`
  + the staged artifact path) WITHOUT spending any seat; the driving session runs its native sub-agent with the
  request's instructions and writes `<out>/native-fill/claude.md`; the same command with
  `--native-leg claude=<file>` runs the other seats and counts the fill (D2). `governed_board_gate` and
  `run_governed_premerge_loop` forward `native_leg_fills`.
  Envelope (r2, codex B — the blocking gap): the emit step writes `request.json` (request_id, seat_key, model,
  lens, effort, artifact_sha256, brief_sha256, `artifact_path`, `instructions_path`, board composition) AND
  stages the exact bundle bytes at `artifact_path` (gemini B). The driving session writes the review text to
  `claude.md` next to it. `--native-leg claude=<dir-or-request.json>` loads the PAIR: `load_native_leg_fill`
  takes every digest from the EMITTED request.json, never from the current invocation. Invocation then
  compares the emitted binding against the actually staged artifact, the resolved instructions and the
  composed seat (seat_key/model), and refuses stale input (`native_fill_stale_request`) BEFORE any other
  seat is spent. Digests are always over CONTENT (staged artifact bytes, resolved brief text), never over
  `artifact_ref` / `brief_ref` paths (grok E). The emit arm never calls today's invoking gate (grok B):
  `governed_board_gate(emit_native_request=True)` performs the same composition, author exclusion, floor
  and staging the invoke arm will redo, builds the request with `native_fill_request_payload`, and returns
  WITHOUT minting an authorization or calling `invoke_board`. Bytes (r2, claude 3): every digest in this plan is over the READ-BACK staged text (write,
  then `read_text`, exactly as `governed_board_gate` mints since agent-harness#914), never the in-memory
  string, so universal-newline normalisation cannot diverge emit from invoke; the emit arm persists the
  artifact and request under `<out>/native-fill/<request_id>/` (advisor-board: `--native-fill-dir`, default
  next to the artifact; run-train: `<ledger-dir>/native-fill/<request_id>/`), NOT in the gate's scratch,
  which is removed in its `finally`. For `run-train`, whose bundle comes from a LIVE PR/workspace read
  (`train_runner` Step 3 + the review-only guards), the invoke step rebuilds the bundle from the CURRENT
  ledger and admitted heads, read-back-normalises it, and compares it to the emitted artifact: a train that
  moved between the two commands is refused (`native_fill_stale_request`) before any seat is spent, so a
  frozen artifact can never approve a state it no longer represents. The determinism claim is therefore
  "identical inputs give identical bytes", enforced by comparison, not assumed. Alternative considered and rejected: an in-run
  mailbox the runtime polls while other seats run — it couples the HARDEN leg lifetime to the driving session's
  reaction time and needs a background launch plus a watcher; the two-phase protocol has no timing.
- **D4 Prose in lockstep.** The claude-* skills that carry seat prose — `claude-advisor-board`,
  `claude-plan-phase`, `claude-execute-phase` (their governed-review paragraphs) and `claude-run-train`
  (the review-only protocol) — state the native-fill protocol. The non-native skills (codex/gemini/opencode
  advisor-board) keep their ROUTE prose unchanged (the self-PTY adapter is their route) but their DESCRIPTION
  of Claude Code ("inside Claude Code … no native-fill request", codex-advisor-board ~:131 and the gemini/
  opencode item 7) is corrected in the same PR (claude 10): a description the change makes false is not
  "unchanged prose".
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
- `invoke_board` early `native_host_deferral_only` return — modify — same detail/request change as the matrix;
  fills applied before its return (r2).
- `NativeLegFill` (frozen dataclass) + `load_native_leg_fill(request_json, review_md)` (digests from the
  EMITTED request only) + `attach_native_fill_provenance` — add.
- `apply_native_leg_fills(board, legs, fills, *, staged_artifact_sha256, brief_sha256)` — add — the D2
  ingestion contract as one pure function (typed refusals, once-per-seat, verdict-contract status).
- `native_fill_request_payload(board, artifact, brief_ref, …)` — add — the emit-side dict (D3), pure.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `advisor-board` — modify — `--emit-native-request [--native-fill-dir <dir>]` and repeatable
  `--native-leg <seat>=<dir-or-request.json>`; the JSON payload reports `native_fill` per leg.
- `run-train` — modify — same two flags, valid only with `--governed --review-only`.

### `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `governed_premerge.py`, `train_runner.py` (modify)
- `governed_board_gate(native_leg_fills=None, emit_native_request=False)` — modify — forward fills to
  `invoke_board`; the emit arm returns the request without invoking.
- `_default_train_review(artifact, run_mode, *, canonical_repo_authority, native_leg_fills=None,
  emit_native_request=False)` — modify — the frozen two-arg `train_review_fn(bundle_text, run_mode)` seam is
  kept; the coordinator binds fills/emit via `functools.partial` exactly as it binds the authority today
  (grok D: PR-1 alone cannot make `run-train` count the seat without this thread).
- `run_governed_premerge_loop(native_leg_fills=None)` — modify — forward on the `invoke` seam only when set.
- `run_train(review_only, emit_native_request, native_leg_fills)` — modify — emit arm stages the exact
  bundle and returns `{"status": "native_fill_requested", "request_path", "artifact_path"}` before any board;
  the invoke arm rebuilds the bundle from the current ledger and refuses a moved train
  (`native_fill_stale_request`) before spending a seat; fills forwarded.

### `phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py` (modify)
- `_classify_reviewtruth_transition` — modify — the `pending` arm also accepts
  `UNAVAILABLE/under_claude_code`; `resolved` unchanged (see D1).

### `phase-loop-runtime/tests/test_native_claude_seat_fill.py` (create)
- routing under Claude Code for fable/opus seats (request attached, detail `under_claude_code`); outside
  Claude Code unchanged (adapter route, `native_adapter_required` builder unchanged); D2 acceptance (counts,
  4/4 usable, floor honoured); digest mismatch refused; fill for a non-deferred seat refused; no spawn and no
  authority constructed for a fill; emit arm spends no seat (spawn = never-called sentinel); `run-train`
  emit → fill → invoke end to end through the REAL `invoke_board` and REAL authorization under the sanctioned
  factory-replacement seam on a mixed-vendor board where claude is eligible (4/4), and a board where the
  author vendor is claude (the fill cannot restore an excluded seat); BOTH deferral paths (production-shaped
  `spawn=None` early return, and the per-seat matrix); CLI-level staleness: emit for artifact/brief A, change
  the ledger or brief to B, submit A's fill → typed refusal with ZERO reviewer launches; duplicate-seat
  refusal; fill for a runtime-produced seat refused; fill without a conforming verdict → DEGRADED, not
  usable; loader never stamps current digests onto an old review; `roadmap_assumptions` `pending` with the
  new token and `resolved` producible; CLI flag validation.

## Documentation impact
- `skills-src/claude/claude-advisor-board/SKILL.md` — modify — replace the two inversion paragraphs with the
  emit → native sub-agent → `--native-leg` protocol; regenerate `phase-loop-skills/` and `skills_bundle/`.
- `skills-src/claude/claude-run-train/SKILL.md` — modify — the review-only protocol under Claude Code.
- `CHANGELOG.md` — modify — Unreleased entry naming agent-harness#396/#636.
- `docs/advisor-board-capabilities-card.md` — modify — the Claude Code row.

## Dependencies & order (r2)
1. PR-1 — the machinery with NO routing change: `NativeLegFill`, request/artifact persistence, the loader
   (emitted digests only), `apply_native_leg_fills` on both deferral paths before the president step, the
   `advisor-board` and `run-train` flags, gate/loop forwarding, and their tests driven by INJECTED
   `under_claude_code` deferrals. Under Claude Code nothing observable changes yet (the seat still defers as
   today), so the LEGIBLE probe stays `pending`.
2. PR-2 — the routing flip on both paths (token `under_claude_code`, request attached for TUI-policy seats),
   the claude skill protocol prose, the non-native skills' corrected description of Claude Code, the
   token-pinning test updates, and `Closes` agent-harness#396 / #636 in the same merge so the probe moves
   from `pending` straight to `resolved`.
Two PRs keep each under the review size that converged on agent-harness#914.

## Verification
```
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python -m pytest -q \
  phase-loop-runtime/tests/test_native_claude_seat_fill.py \
  phase-loop-runtime/tests/test_panel_native_fill_183.py phase-loop-runtime/tests/test_panel_invoker*.py \
  phase-loop-runtime/tests/test_advisor_board*.py phase-loop-runtime/tests/test_governed_*.py \
  phase-loop-runtime/tests/test_train_*.py phase-loop-runtime/tests/test_legible_evidence.py \
  phase-loop-runtime/tests/test_legible_roadmap_contract.py phase-loop-runtime/tests/test_legible_review_repairs.py \
  phase-loop-runtime/tests/test_govlean_roadmap_reseal.py phase-loop-runtime/tests/test_cli*.py
# (r2) every file above exists on main; the earlier globs missed the suites that pin the inversion
# live, under Claude Code, from a git toplevel: emit → fill natively → invoke; expect 4 usable legs
phase-loop advisor-board --board code-review --artifact <bundle> --emit-native-request --json
phase-loop advisor-board --board code-review --artifact <bundle> --native-leg claude=<fill> --json
```
Mutants that must fail: request no longer attached for a fable seat (on EACH deferral path); the
artifact-digest check removed AND, separately, the brief-digest check removed (claude 11: two tests, not one
"digest mismatch"); loader stamps current digests instead of the emitted ones; fill accepted for a non-deferred or
already-filled seat; fill status forced OK without a verdict; emit arm spawns; train invoke arm skips the
moved-train comparison; outside-Claude-Code route changed.

## Acceptance criteria
- [ ] Under Claude Code, `invoke_board(CODE_REVIEW_BOARD, …)` returns the claude seat `UNAVAILABLE/under_claude_code` with `needs_native_agent` set, for the default (fable) seat.
- [ ] A supplied fill whose EMITTED digests match the staged artifact and resolved brief, for a seat deferred as `under_claude_code`, makes the seat usable and the board 4 of 4; a mismatched or stale binding, a non-deferred seat, a duplicate, or a fill without a conforming verdict is a typed refusal or DEGRADED, with zero reviewer launches on a refusal.
- [ ] `run-train --governed --review-only --emit-native-request` spends no seat and writes the request; with `--native-leg claude=<file>` the approval record's `usable_reviewers` counts the fill.
- [ ] Outside Claude Code every existing panel/board test is byte-identical in outcome; `native_agent_leg_request(env=<non-Claude>)` still raises for TUI-policy models.
- [ ] The claude-* skills that carry seat prose describe the protocol; the codex/gemini/opencode skills keep their adapter ROUTE prose byte-identical while their description of Claude Code no longer promises "no native-fill request".
- [ ] `roadmap_assumptions._classify_reviewtruth_transition` is byte-identical; after PR-2 merges with the issues closed, a live observation under Claude Code satisfies its `resolved` arm.
