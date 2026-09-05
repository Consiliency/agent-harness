# Decision note — interim ratification of president-gated landing tiers

**Date:** 2026-09-04
**Anchor:** `origin/main` @ `c567c01c`
**Decided by:** the maintainer (operator ruling, relayed by the operator's claude session)
**Decision:** **Until a HARDEN-authorized president execution operation exists
(Consiliency/agent-harness#752), the `plan` and `production_code` landing tiers land on
four-seat cross-vendor convergence with no president ruling.** This is an explicit, dated,
expiring exception recorded here — not a change to the runtime default and not a silent
bypass.

## Why an exception is needed

`review_policy_for_tier` (`phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`)
answers the `plan` and `production_code` tiers with `requires_president=True`, as
EC-GOVLEAN-5 mandates ("full board plus president for production-code and plan landings").
Since Consiliency/agent-harness#750 (ah#736) a president-requiring policy also requires a
president seam, and the only adapter (`president_adapter.build_president_invoke`) answers
every seated rung with `president_execution_route_unavailable` — by design, because
post-HARDEN (EC-HARDEN-5) the only production execution operation is the governed review
and a president ruling's terminal grammar (`FORCING DECISION:`) is not that operation's
grammar. The adapter's docstring names the replacement: a HARDEN-authorized president
operation with its own mode, brief, completion grammar, and authorization identity. That
operation does not exist yet.

The consequence, measured on 2026-09-04: every plan- and production-code-tier landing fails
closed by construction. Four converged PRs (Consiliency/agent-harness#765, #768, #769,
#771) sat parked with 4/4 AGREE recorded and no path to `main`. The maintainer's ruling:
"What about the failure to merge any work" → interim ratification.

## What the exception is

- **Scope.** Landings whose review tier is `plan` or `production_code` under the GOVLEAN
  authority switch (in force for agent-harness).
- **Bar.** The full four-vendor board (`fable`, `sol`, `gemini`, `grok`) must converge
  4/4 AGREE on the landing head under the advisor-board skill's review-round rules (which
  seats re-review after a delta, the round cap, and what "exact head" means are defined
  there, not here). Nothing below the full board is admitted; the exception removes only
  the president ruling, not any seat.
- **Mechanism.** The landing caller passes an explicit
  `ReviewLandingPolicy(required_seats=("fable", "sol", "gemini", "grok"),
  requires_president=False)` to `invoke_board`. `review_policy_for_tier` is NOT changed:
  the tier default and the `landing_tier=` path still require a president and still fail
  closed. The exception is reachable only by constructing that policy by hand, and the
  runtime does not know this note exists: nothing binds the override to a citation or a
  ledger row. Citing this note and appending the ledger row are recording obligations on
  the operator performing the landing, enforced by review of that landing's PR body, not
  by code. Stated plainly: for every landing in the ledger below, EC-GOVLEAN-5's "full
  board plus president" mandate is not met; the runtime's frozen controls stay green
  because the runtime is unchanged, not because the mandate is satisfied. This note is a
  procedural exception — a documented, dated bypass of the president ruling with the
  maintainer's authority behind it — until the roadmap carrier lands.
- **Record.** Every landing performed under this exception cites this note in its PR
  body and appends itself to the ledger below (append-only; do not rewrite earlier rows).
- **Expiry.** The exception ends the moment the president operation from
  Consiliency/agent-harness#752 lands on `main`. Because the default was never changed,
  nothing in the runtime needs reverting — but nothing in the runtime stops a caller from
  continuing to hand-construct `requires_president=False` either. So expiry is a closing
  action, not a passive event: the PR that lands ah#752 MUST, in the same PR, append a
  final `EXPIRED by Consiliency/agent-harness#<that PR's number>` row to the ledger below
  and mark this note closed (the PR number is known before merge; the merge commit is
  not, so the row is keyed on the PR, not the commit). Expiry takes effect when that PR
  merges to `main` — not when the row is written, and not later. ah#752's issue body
  carries that obligation. From that merge on, any `plan`/`production_code` landing that
  passes `requires_president=False` is a governance violation to be raised on the landing
  PR, and any launcher script that still hard-codes the override (the operator's
  standalone `invoke_board` launchers) is to be deleted or switched to `landing_tier=`.
  This note stays as history.

## What this does NOT change

- The roadmap `specs/phase-plans-v10.md` is LEGIBLE-owned and is not edited here. The
  roadmap-text carrier for this exception is Consiliency/agent-harness#688 (roadmap edit
  proposal); this note is the operator record until that lands.
- The president availability ladder, ruling grammar, and typed-refusal behaviour
  (`president_ruling_missing`, `president_execution_route_unavailable`) are unchanged.
- `tests_only` / `docs_only` tiers (single grounded reviewer) are unchanged.
- EC-HARDEN-5: no execution route is added for president rulings; nothing routes around
  `harden_advisory_execution_refused`.

## Ledger of landings under this exception

| PR | Tier | Landing head | Board record |
|---|---|---|---|
| Consiliency/agent-harness#765 | plan | `08acf487` | r1 grok/gemini AGREE, codex/claude DISAGREE (2 findings); delta r2 codex/claude AGREE → 4/4 |
| Consiliency/agent-harness#768 | production_code | `5277cd6f` | r1 3 AGREE + fable PARTIALLY AGREE (2 findings addressed); exact-head delta 4/4 AGREE (recorded in PR body) |
| Consiliency/agent-harness#769 | plan | `e205cfa7` | exact-head plan board 4/4 AGREE (recorded in PR body) |
| Consiliency/agent-harness#771 | tests_only (not under this exception; listed because it is the stack leaf) | `b50f0b99` | fresh four-vendor 4/4 AGREE (recorded in PR body), exceeding the tier's single-grounded-reviewer bar |
| Consiliency/agent-harness#777 | production_code | exact head recorded in the PR body | four-vendor board, `requires_president=False` (record in PR body) |
| Consiliency/agent-harness#786 | production_code | exact head recorded in the PR body | four-vendor board, `requires_president=False`; landing conditional on 4/4 exact-head AGREE and required CI (record in PR body) |
