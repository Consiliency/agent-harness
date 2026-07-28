# Detailed plan: ah#358 — board silent degradation (decision-scoped)

**Status:** DRAFT — awaiting cross-vendor panel
**Date:** 2026-07-28
**Issue:** Consiliency/agent-harness#358 (consolidates #346, #332, #356, #319)

> **Scope note.** This plan is deliberately **decision-scoped**. It frames four forks and
> recommends one branch each. It does NOT specify implementation. The panel should argue
> the forks; pseudocode would only invite review of the wrong layer.

## Task

The cross-vendor board is this repo's merge gate. It can lose seats and report normally.
Three real pre-merge boards on 2026-07-28 (#354, #351, and the #226/#212/#105 queue drain)
each returned **3 OK seats against a declared floor of 3, `native_fill_requests: 0`, and no
degradation signal to the caller**. On #105 two seats voted AGREE on a PR that fails CI on
five gates and introduces an `UnboundLocalError` on the path it was written to fix.

## Research summary (verified in-session, not recalled)

- `governed_review._findings_from_panel` (`governed_review.py:117`) keys BLOCK-vs-WARN on
  `leg.text.strip()`. Empty ⇒ `panel_leg_degraded` ⇒ **WARN**; non-empty ⇒
  `panel_nonconforming` ⇒ **BLOCK**. One predicate is answering two different questions:
  *did the seat run* and *did the seat review*.
- It gates a live path: `governed_review.py:265` is the governed pre-merge consumer.
- `compose_review_board()` seats claude at `claude-fable-5`.
  `_claude_tui_policy_model('claude-fable-5')` is **True** (also `claude-opus-4-8`,
  `claude-opus-5`; `claude-sonnet-5` is **False**). The native-fill guard
  (`panel_invoker.py:~4172`) requires `not _claude_tui_policy_model(seat.model)`, so on the
  default board **no `NativeAgentLegRequest` is ever emitted**. Inside Harness Code the TUI
  adapter cannot run, so that seat is always UNAVAILABLE.
- `test_advisor_board_golden.py` asserts per-leg **argv + scrubbed env + timeout
  byte-equality** between `invoke_panel(artifact, PANEL_LEGS)` and
  `invoke_board(DEFAULT_BOARD)`, with **`seat_key` as the one contract-sanctioned delta**
  (`:25-30`, `:109`, `:173`).

## Decisions

### D1 — How is seat usability represented, given the frozen golden contract?

Keying on `text` is the root defect (#346 and #332 are its two directions). The fix is a
typed seat outcome — but `PanelLegResult` sits under a byte-equality proof whose docstring
names `seat_key` as the single sanctioned additive delta.

- **(a) Add a typed `outcome` field as a SECOND sanctioned additive delta.** Extend the
  golden's documented delta list; the proof continues to assert byte-equality of argv/env/
  timeout, which is what it actually protects.
- **(b) Derive outcome without a schema change** (a helper reading status+detail+text).
  No contract change, but leaves `text` load-bearing and re-opens the same defect at the
  next caller.
- **(c) Restructure the golden proof** to assert the spawn contract only, decoupled from
  result shape.

**Recommendation: (a).** The golden protects the *spawn* contract (what we send vendors),
not the *result* shape. `seat_key` already established additive-delta precedent. (b) is the
false economy that produced this bug. (c) is a larger change to a proof that is currently
load-bearing and correct.

**Panel question:** is extending the sanctioned-delta list a contract amendment requiring
its own sign-off, and does the golden's docstring need to become normative about which
deltas are permitted?

### D2 — Does a sub-floor board BLOCK or WARN?

**This is the fork I smuggled into #358's acceptance criteria as "fail loud below floor"
without noticing it was a decision.** It collides with a standing repo principle: *review
gates default soft/warn, opt-in to block, never add `human_required`.*

- **(a) BLOCK below floor.** Strongest integrity; contradicts autonomy-first and can wedge
  an autonomous run when a vendor is transiently down.
- **(b) WARN loudly + typed signal, opt-in to block** via existing enforce-mode env
  (precedent: `PHASE_LOOP_ACCEPTANCE_ENFORCE`, ah#246).
- **(c) WARN, but make convergence UNCLAIMABLE below floor** — the run proceeds; what it
  may not do is *report convergence*. Separates "halt the pipeline" from "certify a gate."

**Recommendation: (c), with (b)'s env as the opt-in to hard block.** The actual harm tonight
was not that runs continued — it was that a degraded board was indistinguishable from a
clean one, so admin-merge authorization rested on a claim the board could not support.
Removing the false claim addresses the harm without violating autonomy-first.

**Panel question:** is "convergence unclaimable" enforceable at the type level, or does it
degrade into prose that the next caller ignores?

### D3 — What fills the claude seat inside Harness Code?

- **(a) Seat a native-fill-eligible model** (`claude-sonnet-5`) under a driving host.
  Satisfies the fill requirement — but silently changes what the *correctness* seat is, and
  a weaker model on the seat that most often dissents is a real cost.
- **(b) Backfill a 4th lens-distinct seat onto an available non-claude vendor.** Preserves
  four real reviewers and lens diversity; loses same-vendor coverage.
- **(c) Emit a typed `seat_unfillable` signal and run 3-of-4 honestly.**

**Recommendation: (b) + (c).** They compose: signal the unfillable seat AND backfill the
lens, so the board is both honest and full. (a) trades reviewer quality for a checkbox on
the seat that has been carrying the most signal.

**Panel question:** does lens-distinct backfill onto one vendor create correlated blind
spots that make 4 seats weaker than an honest 3?

### D4 — #319 three-tuple degradation

`invoke_board` degrades a seat with `too many values to unpack (expected 2)` when
`_default_spawn_via_provider()` returns the additive `(status, text, detail)` tuple.
**Not a decision — mechanical.** Include in scope; it is another path that silently converts
a working seat into a non-seat.

## Documentation impact

- `CHANGELOG.md` — required (public-surface behavior change; docs-freshness CI gate).
- `test_advisor_board_golden.py` docstring — if D1(a), the sanctioned-delta list becomes
  normative and must say so.
- advisor-board SKILL.md copies (4 harness variants + `phase-loop-skills/` + bundled
  `skills_bundle/`) — only if operator-visible board semantics change. Partial edits across
  those copies are a known defect class here; regen + sync, do not hand-edit one.

## Dependencies & order

1. **D1 first.** D2 and D3 both need a typed outcome to express themselves.
2. **D2 and D3 are independent** of each other once D1 lands.
3. **D4 any time** — isolated.
4. **ah#359 (leg lifecycle) is DOWNSTREAM.** Until the board reports degradation honestly,
   a timeout/orphan bug is indistinguishable from a clean run.

## Verification

```bash
PYTHONPATH=phase-loop-runtime/src python3 -m pytest phase-loop-runtime/tests \
  -q -k "board or panel or governed" -p no:randomly
PYTHONPATH=phase-loop-runtime/src python3 -m pytest \
  phase-loop-runtime/tests/test_advisor_board_golden.py -q     # contract must still hold
ruff check phase-loop-runtime/src/phase_loop_runtime/
```

Plus a live board run from inside Harness Code, asserting it yields four reviewing seats OR
a typed unfillable signal — never a silent 3-of-4.

## Acceptance criteria

- [ ] A board below its declared **reviewed-seat** floor cannot report convergence
- [ ] An unusable leg is distinguished from a reviewing leg **without inspecting `text`**
- [ ] A spawn that RAISES does not produce a governed BLOCK from its traceback
- [ ] A board driven inside Harness Code yields 4 reviewing seats or a typed unfillable
      signal
- [ ] `test_advisor_board_golden.py` still passes, or its sanctioned-delta list is
      explicitly and normatively amended
- [ ] Every test names a mutation that was **RUN**, with the injection anchor asserted so a
      mutation that fails to apply cannot masquerade as a pass

## Known trap for the implementer

The GC precedent from ah#354: a guard was added and the code **eight lines later** undid it
unconditionally, and a pre-existing test asserted the resulting data loss as intended. When
you add a seat-outcome guard, read what runs after it in the same function, and grep for
existing tests that pin the current (defective) behavior — changing such a test is a panel
question, not an author's judgement.
