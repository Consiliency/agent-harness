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

### D2 — [SUPERSEDED by panel round 1 — see D2′] Does a sub-floor board BLOCK or WARN?

> **RETRACTED 2026-07-28 after panel round 1 (codex DISAGREE, gemini DISAGREE).**
> Two independent errors, both mine:
>
> 1. **It proposed inventing a mechanism that already ships.**
>    `ratification_policy.RatificationPolicy` already models `required_vendors`,
>    `required_lens_coverage`, `required_consensus` (`unanimous`|`majority`), and
>    `on_shortfall` (`escalate` | `proceed_degraded`) — and explicitly preserves
>    autonomy-first ("never a `human_required` stall"), citing the same guardrail I cited
>    as the reason to invent something new. `gate_posture.py:130` already provides the
>    manifest-level shortfall override.
> 2. **I cited a false precedent.** `PHASE_LOOP_ACCEPTANCE_ENFORCE` is a GOAL-COVERAGE
>    control (`runner.py:6234`), not review ratification. It is not precedent for this at all.
>
> Original text retained below for the record; do not implement it.

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

### D2′ — Wire the EXISTING `RatificationDecision` into merge authorization

Do not invent a floor rule. `RatificationPolicy` already expresses it. The decision is
**where its verdict becomes authoritative**: only `ratified` may be called convergence, and
only `ratified` may authorize admin-merge. `proceed_degraded` proceeds AND writes a durable
audit record — it is explicitly not convergence.

**Panel question:** is `RatificationDecision` currently reachable from the live pre-merge /
merge-authorization path at all, or is it composed-but-never-dispatched (the same shape as
`invoke_board` before it was wired)? If the latter, wiring it IS the fix.

### D2″ — Three states, not two (the motivating failure is AT floor, not below it)

**This is the finding that invalidates the plan's original acceptance criteria.** Measured
across every board this session:

| board | reviewed seats | floor | below floor? |
|---|---|---|---|
| ah#354 | 3 | 3 | **no** |
| ah#351 | 3 | 3 | **no** |
| #226/#212/#105 queue | 3 | 3 | **no** |
| this plan's own panel | 2 | 3 | yes (grok DEGRADED) |

Every incident that motivated ah#358 delivered **exactly the floor**. `cli.py:1526` treats 3
as usable and exits successfully. So a "below floor" rule — the original acceptance
criterion — **would not have fired on any of them.** It is a criterion that cannot fail.

Type three distinct states and decide which may authorize merge:
- **full** — target seat count delivered (4)
- **floor-only degraded** — at floor but below target; usable, NOT convergence
- **below floor** — not usable

**Recommendation:** only **full** authorizes admin-merge on a public repo.
**floor-only degraded** may proceed and must say so in every surface that reports the
verdict. This is what actually addresses the observed failures.

### D2‴ — The authoritative voting rule (currently two rules disagree)

`governed_review.py:157` gives **every `DISAGREE` veto power**. `ratification_policy.py:101`
uses **majority consensus**. On the exact case observed this session — two vendors AGREE, codex
DISAGREEs and is right — these produce **opposite outcomes**. The plan must pick one.

**Recommendation: veto (unanimous) for pre-merge on a public repo**, with an explicit
rationale that generalizes: *the board's job is the residue that mechanical checks cannot
decide.* Facts are CI's job. A panel is not voting on facts, so majority agreement carries
much less information than a single well-evidenced dissent. Session evidence: codex's lone
DISAGREE was correct on #354, #351, #212 and #105 — including #105, where two seats AGREE'd
on a change failing five CI gates.

**Must also decide:** do same-vendor backfilled seats (D3) count toward `required_vendors`,
toward lens coverage only, or neither? Counting them toward consensus manufactures
correlated votes and would dilute exactly the dissent that has been carrying the signal.

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

### D5 — D3's backfill CONFLICTS with D1's golden proof (raised by gemini)

Dynamic lens-backfill changes the backfilled seat's **argv**, which is exactly what
`test_advisor_board_golden.py` asserts byte-equal between `invoke_panel(PANEL_LEGS)` and
`invoke_board(DEFAULT_BOARD)`. D1 assumed the proof survives; under D3(b) it does not.

Decide explicitly: does the golden proof bind the **static default board** only (so a
dynamically composed board is out of its scope, stated normatively), or must backfill
preserve byte-equality (which likely forecloses D3(b))? These cannot both hold.

## Acceptance criteria

> **Round-1 note.** The original criterion here was *"a board below its declared floor
> cannot report convergence."* Measured: every board that motivated this issue delivered
> exactly the floor, so that criterion **could not have fired on any of them.** Replaced.

- [ ] Re-running the three motivating boards (ah#354, ah#351, the queue drain) under the new
      rule, each is reported as **floor-only degraded** and **cannot authorize admin-merge**
      — the criterion must fire on the incidents that motivated the work
- [ ] Only `RatificationDecision == ratified` may be called convergence or authorize merge
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
