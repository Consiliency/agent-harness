# Detailed plan: REVIEWTRUTH early slice — native claude seat under Claude Code, counted (EC-REVIEWTRUTH-14; EC-REVIEWTRUTH-1/-4 classification)

- status: proposed (r3 — reframed under the maintainer's 2026-09-20 ratification of an EARLY REVIEWTRUTH slice; folds board rounds 1–2 of agent-harness#918)
- authority: v10 Phase 7 REVIEWTRUTH (`specs/phase-plans-v10.md`), lane plan `plans/phase-plan-v10-REVIEWTRUTH.md` (status committed). This slice executes AHEAD of the phase's recorded SCHED/HARDEN ordering gates under a maintainer waiver scoped to this slice only (recorded on Consiliency/agent-harness#396, 2026-09-20). The rest of REVIEWTRUTH stays behind its gates.
- refs: Consiliency/agent-harness#396, #636, #906 (consumer: the train review of #914 runs 3 of 4 seats under Claude Code), #918 (this plan's PR)
- execute: effort=high, reason=review-seat routing at the HARDEN launch boundary; a floor that gates merges; the phase's live assumption probe

## Task

Deliver the roadmap goals below (referenced, not restated) as one bounded slice:

- **EC-REVIEWTRUTH-14** — the native fill for the TUI-policy claude/fable seat under Claude Code, counted only once the verdict is bound back into the board result.
- **EC-REVIEWTRUTH-4** — a board driven inside Claude Code resolves to FULL / FLOOR-ONLY / BELOW-FLOOR; a silent 3-of-4 reported as FULL is impossible.
- **EC-REVIEWTRUTH-1 (partial)** — the three-state classifier itself, used on the native-fill path; wiring it into every governed gate stays with SL-3/SL-5.

Today (all verified against `main`): `native_agent_leg_request` raises for TUI-policy models, so the default fable seat carries no request; both `invoke_board` deferral paths emit `tui_adapter_required`; the claude skill prose forbids the native fill; nothing lets a driving session hand a fill back; and the phase's live probe cannot reach its `resolved` arm because the LEGIBLE adapter never emits the fields that arm requires.

Non-native hosts keep the self-PTY adapter route, byte-neutral.

## Lane ownership (from the phase plan; this slice touches only these)

| file | lane |
|---|---|
| `panel_invoker.py`, `advisor_board/composition.py` | SL-2 |
| `governed_review.py` | SL-3 |
| `governed_premerge.py`, `cli.py`, `train_runner.py` | SL-5 |
| `legible_evidence.py` (the probe adapter) | LEGIBLE (carried under the same waiver; classifier untouched) |

`IF-0-REVIEWTRUTH-1` (the `PanelLegOutcome` vocabulary and `reviewed_seat_count`) remains SL-2's to publish; this slice does NOT mint a parallel outcome vocabulary — a fill is expressed through today's `status`/`detail` (`detail="native_fill"`) and the three-state classifier reads `usable` legs, so SL-2's later freeze maps onto it without rework.

## Decisions (D1–D6; rounds 1–2 folded)

- **D1 Routing.** Under Claude Code the claude seat — every claude model, TUI-policy included — defers `UNAVAILABLE` with typed detail `under_claude_code` AND carries a `NativeAgentLegRequest`; `native_agent_leg_request` raises for TUI-policy models only when NOT under Claude Code. `under_claude_code` joins `_TYPED_UNAVAILABLE_DETAILS`. BOTH deferral paths change: the per-seat matrix AND the early `native_host_deferral_only and spawn is None` return in `invoke_board`; `tui_backing_required` stays a refusal on both. Outside Claude Code nothing changes (`native_adapter_required` affordance, self-PTY trust gate, scrubbing). No `claude -p`, SDK, API key or alternate endpoint anywhere: a fill is DATA from the first-party session, not a launch. The HARDEN review-mode gate, factory and revalidation run unchanged before either deferral result is built.
- **D2 Fill ingestion contract.** `NativeLegFill(seat_key, model, text, artifact_sha256, brief_sha256, composition_sha256, request_id, filled_by, filled_at)`, loaded ONLY from an emitted `request.json` + `claude.md` pair (digests from the EMITTED request, never from the current invocation). Eligible target: a seat whose runtime result is `UNAVAILABLE/under_claude_code` carrying `needs_native_agent`, matched by `seat_key` and `model`; once per seat; never replaces a runtime result; `tui_backing_required` / support-missing / authentication `UNAVAILABLE`s are NOT fillable. Status from the terminal-verdict contract: OK only when the LAST non-empty line is a conforming verdict, else DEGRADED (never usable). Provenance attached as metadata (never a schema field); the binding defeats SUBSTITUTION (another bundle, brief, composition, a seat the runtime ran, a seat dropped by author exclusion) and does not prove a model produced the text.
  **Refusal timing (codex r2-3):** `preflight_native_leg_fills` runs BEFORE any reviewer launch and refuses — typed, zero launches — duplicates (`native_fill_duplicate_seat`), ineligible seats (`native_fill_seat_not_deferred`: routing would not defer this seat here), digest mismatch (`native_fill_digest_mismatch`, artifact and brief checked separately), composition drift (`native_fill_composition_drift`), and stale requests (`native_fill_stale_request`). `apply_native_leg_fills` then attaches accepted fills to the collected results IMMEDIATELY after every seat has returned and BEFORE `president_findings_from_legs` / `invoke_president` / `PanelResult` assembly, on both paths; the early deferral path no longer returns early once fills exist — it builds its results and joins the common tail (claude r2-B), so the president rules on exactly the legs `usable_legs` counts.
- **D3 Emit → fill → invoke protocol.** `advisor-board --emit-native-request [--native-fill-dir <dir>]` and `run-train --governed --review-only --emit-native-request` perform the same composition, author exclusion, floor and staging the invoke arm will redo, then write `<dir>/native-fill/<request_id>/{request.json, artifact.md, instructions.md}` and return WITHOUT minting an authorization or calling `invoke_board` (`governed_board_gate(emit_native_request=True)` for the train). `request.json` carries request_id, seat_key, model, lens, effort, `artifact_sha256`, `brief_sha256`, `composition_sha256` (over the sorted seat_keys of the composed board), and the paths. The driving session writes `claude.md` beside it. `--native-leg claude=<dir-or-request.json>` loads the pair and runs the invoke arm. All digests are over CONTENT read back from disk (write, then `read_text`, as `governed_board_gate` mints since #914), never over paths; artifacts persist under the caller's dir (train: `<ledger-dir>/native-fill/`), never in the gate's rmtree'd scratch. The invoke arm re-composes, re-stages (the train arm REBUILDS the bundle from the current ledger and admitted heads) and compares emitted vs actual artifact, brief, composition and seat before spending any seat. No re-spend, no in-run mailbox (rejected: it couples HARDEN leg lifetime to the driving session's reaction time). `governed_board_gate(native_leg_fills=…)`, `run_governed_premerge_loop(native_leg_fills=…)` and `_default_train_review(…, native_leg_fills=…, emit_native_request=…)` forward on the existing seams; the frozen two-arg `train_review_fn(bundle_text, run_mode)` surface is kept via `functools.partial`, as the authority is bound today.
- **D4 Three-state classification (EC-REVIEWTRUTH-1/-4).** `classify_board_delivery(board, panel) -> "FULL" | "FLOOR_ONLY" | "BELOW_FLOOR"` in `governed_review.py` (SL-3): FULL when usable seats == `DEFAULT_TARGET_SEATS`, FLOOR_ONLY when `FLOOR_SEATS <= usable < target` (carrying the typed shortfall: the deferred seat's request, or its typed unavailability), BELOW_FLOOR below the floor. `governed_board_gate` records it on the `GateResult` (`delivery` field, additive) and the premerge loop surfaces it; a FLOOR_ONLY board may proceed under today's floor but is never reported as FULL. A natively filled seat counts toward FULL only once its verdict is bound (D2). This is the classifier EC-1 names; its use at every governed gate remains SL-3/SL-5.
- **D5 The phase's live probe (LEGIBLE-A3) — two-phase under Claude Code (grok/claude/gemini/codex r2).** `roadmap_assumptions._classify_reviewtruth_transition` and `legible_evidence._flatten_reviewtruth_observation` are BYTE-IDENTICAL. `run_reviewtruth_fable_probe(repo, …, native_leg_fills=None)` under Claude Code becomes the emit → fill → invoke protocol on the fixed probe artifact with `CODE_REVIEW_BOARD`: without a fill it returns a typed `FableProbeRecord(kind="fill_requested", request_path=…)` — an INCOMPLETE observation the assumption-probe caller records as "fill requested" and can neither pass nor classify (it never reaches the classifier, so `None` is unreachable); with a fill it runs the real board and emits `native_fill_request` (from `needs_native_agent`), `verdict_bound` (the fill was applied under D2's binding), `seat_count` (D4's state, `FULL` or `degraded` in the flattener's vocabulary) plus today's fields. Outside Claude Code the single-leg adapter is unchanged. The issue snapshot is injectable so PR-2's tests exercise both arms; the LIVE probe is an operator instrument run against `main`, not a pre-merge CI check, so the PR-2 branch state is never observed live. Sequencing: PR-1 changes no routing (probe stays `pending`); PR-2 lands the routing flip, the two-phase probe and `Closes` #396/#636 in one merge; the first complete post-merge observation satisfies `resolved`.
- **D6 Prose in lockstep.** `claude-advisor-board`, `claude-plan-phase`, `claude-execute-phase` (their governed-review paragraphs) and `claude-run-train` state the protocol; `codex-/gemini-/opencode-advisor-board` keep their ROUTE prose byte-identical but their DESCRIPTION of Claude Code ("no native-fill request") is corrected; `docs/advisor-board-capabilities-card.md` Claude Code row; CHANGELOG.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (SL-2, modify)
- `native_agent_leg_request` — modify — raise for TUI-policy models only when `not _under_claude_code(env)`.
- `_exec_claude_tui_leg` — modify — under Claude Code return `("UNAVAILABLE", "under_claude_code")`.
- `_TYPED_UNAVAILABLE_DETAILS` — modify — add `under_claude_code`.
- `invoke_board` — modify — accept `native_leg_fills`; both deferral paths attach the request for every claude seat under Claude Code; `preflight_native_leg_fills` before any launch; `apply_native_leg_fills` after results, before the president step; the early deferral path joins the common tail.
- `NativeLegFill`, `load_native_leg_fill(request_json, review_md)`, `native_fill_request_payload(...)`, `preflight_native_leg_fills(...)`, `apply_native_leg_fills(...)`, `attach_native_fill_provenance` — add (pure; no spawn, no authority).

### `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py` (SL-2, modify)
- `composition_digest(board) -> str` — add — sha256 over the sorted seat_keys (used by D2/D3).

### `phase-loop-runtime/src/phase_loop_runtime/governed_review.py` (SL-3, modify)
- `governed_board_gate(native_leg_fills=None, emit_native_request=False)` — modify; `classify_board_delivery` — add; `GateResult.delivery` — add (additive, default None).

### `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `train_runner.py`, `cli.py` (SL-5, modify)
- `run_governed_premerge_loop(native_leg_fills=None)` — forward when set; surface `delivery`.
- `_default_train_review(..., native_leg_fills=None, emit_native_request=False)`; `run_train(review_only, emit_native_request, native_leg_fills)` — emit arm stages under `<ledger-dir>/native-fill/` and returns `native_fill_requested`; invoke arm rebuilds and compares before any seat.
- `advisor-board --emit-native-request [--native-fill-dir]`, `--native-leg <seat>=<dir-or-request.json>` (repeatable, duplicates refused); `run-train` the same two flags, valid only with `--governed --review-only`; JSON payloads report `native_fill` and `delivery`.

### `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py` (LEGIBLE, modify)
- `run_reviewtruth_fable_probe(..., native_leg_fills=None, issue_snapshot=None)` and `_invoke_reviewtruth_fable_adapter` — modify — D5 two-phase observation under Claude Code; `FableProbeRecord.kind` — add (`observation` | `fill_requested`). `_flatten_reviewtruth_observation` — unchanged. `roadmap_assumptions.py` — unchanged.

### Tests (create `phase-loop-runtime/tests/test_native_claude_seat_fill.py`; update the pinning suites)
- Routing under Claude Code on BOTH paths (production-shaped `spawn=None` early return; per-seat matrix) for fable/opus seats: request attached, detail `under_claude_code`; outside Claude Code byte-identical; `native_agent_leg_request(env={})` still raises for TUI-policy models.
- Ingestion: fill counts (4/4 FULL) on a mixed board through the REAL `invoke_board` + REAL authorization under the sanctioned factory-replacement seam; a board where claude is the author vendor (the fill cannot restore an excluded seat); duplicate, non-deferred, runtime-produced, backing-refused, no-verdict (DEGRADED), artifact-digest, brief-digest, composition-drift and stale-request cases, each with ZERO reviewer launches on refusal; loader never stamps current digests; president sees the filled leg (a president-requiring policy on the early path).
- Classification: FULL / FLOOR_ONLY / BELOW_FLOOR with a typed shortfall; a lost fill preserves FLOOR_ONLY.
- Protocol: `advisor-board` and `run-train` emit → fill → invoke end to end; emit spends no seat; CLI staleness (emit for A, move the ledger/brief to B, submit A's fill → typed refusal, zero launches); flag validation.
- Probe: `fill_requested` incomplete record under Claude Code without a fill; a complete filled observation classifies `resolved` with an injected CLOSED snapshot; `pending` unchanged outside Claude Code; classifier/flattener byte-identical (a test asserts their source digests).
- Pinning suites updated for the Claude Code case only: `test_panel_native_fill_183.py` (its "load-bearing SECURITY" tests inverted, not kept), `test_panel_invoker_spawn.py`, `test_legible_evidence.py`, `test_legible_roadmap_contract.py`, `test_legible_review_repairs.py`, `test_govlean_roadmap_reseal.py`.

## Documentation impact
- `skills-src/claude/{claude-advisor-board,claude-plan-phase,claude-execute-phase,claude-run-train}/SKILL.md` — modify (D6); regenerate `phase-loop-skills/` and `skills_bundle/`.
- `skills-src/{codex,gemini,opencode}/*-advisor-board/SKILL.md` — modify — Claude Code description only.
- `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md` — modify.

## Dependencies & order
1. **PR-1 — machinery, no routing change:** `NativeLegFill`, request/artifact persistence, loader, `composition_digest`, `preflight_native_leg_fills`, `apply_native_leg_fills` on both paths before the president step, `classify_board_delivery`, the `advisor-board` / `run-train` flags, gate/loop/train forwarding, tests driven by INJECTED `under_claude_code` deferrals. Under Claude Code nothing observable changes; the probe stays `pending`.
2. **PR-2 — routing flip + probe + prose + closure:** D1 on both paths, the two-phase probe (D5), the pinning-suite inversions, the skill and card prose (D6), and `Closes` Consiliency/agent-harness#396 / #636 in the same merge.

## Verification
```
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python -m pytest -q \
  phase-loop-runtime/tests/test_native_claude_seat_fill.py phase-loop-runtime/tests/test_panel_native_fill_183.py \
  phase-loop-runtime/tests/test_panel_invoker*.py phase-loop-runtime/tests/test_advisor_board*.py \
  phase-loop-runtime/tests/test_governed_*.py phase-loop-runtime/tests/test_train_*.py \
  phase-loop-runtime/tests/test_legible_evidence.py phase-loop-runtime/tests/test_legible_roadmap_contract.py \
  phase-loop-runtime/tests/test_legible_review_repairs.py phase-loop-runtime/tests/test_govlean_roadmap_reseal.py \
  phase-loop-runtime/tests/test_cli*.py
# live, under Claude Code, from a git toplevel (after PR-2): emit → fill natively → invoke → 4 usable, delivery FULL
phase-loop advisor-board --board code-review --artifact <bundle> --emit-native-request --json
phase-loop advisor-board --board code-review --artifact <bundle> --native-leg claude=<dir> --json
```
Mutants that must fail: request not attached on EITHER path; artifact-digest check removed; brief-digest check removed; composition check removed; loader stamps current digests; duplicate accepted; non-deferred seat filled; fill status forced OK without a verdict; fills applied after the president step; early path still returns before the president; emit arm launches; train invoke arm skips the rebuild comparison; probe classifies an unfilled Claude Code observation; classifier or flattener source changed; outside-Claude-Code route changed.

## Acceptance criteria
- [ ] EC-REVIEWTRUTH-14 — proven by `test_native_claude_seat_fill.py` (request emitted for the default fable seat under Claude Code on both paths; a bound fill classifies FULL alongside 3 CLI seats; a dropped fill preserves FLOOR_ONLY; no request outside Claude Code or without a fable seat) and the live `advisor-board` emit → fill → invoke run above.
- [ ] EC-REVIEWTRUTH-4 — proven by the FULL / FLOOR_ONLY / BELOW_FLOOR tests for a board driven under Claude Code; a silent 3-of-4 FULL is unreachable.
- [ ] EC-REVIEWTRUTH-1 (partial: the classifier) — proven by `classify_board_delivery` tests on the three states with a typed shortfall; full gate wiring stays with SL-3/SL-5 and is NOT claimed here.
- [ ] Every refused fill (duplicate, ineligible, digest, composition, stale) is typed and launches zero reviewers; every accepted fill is visible to the president before any ruling.
- [ ] `roadmap_assumptions._classify_reviewtruth_transition` and `_flatten_reviewtruth_observation` are byte-identical; under Claude Code an unfilled probe returns `fill_requested` (never `None`), and a filled probe with the issues closed satisfies `resolved`.
- [ ] Non-native route byte-identical in outcome across the existing panel/board suites; the non-native skills' route prose is byte-identical while their Claude Code description no longer promises "no native-fill request".
