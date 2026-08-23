# Active file claims — a Claude-session handoff log

**Read this before believing the title.** This is a durable log of what Claude sessions
are touching. It is **not** cross-agent coordination today, and it is **not** the fix for
roadmap-ownership mistakes. Both of those were the original framing and both were
overstated; a review panel called it and was right.

**Why it is not cross-agent:** the agent most likely to collide with — the Codex agent —
cannot participate. Its message-board membership is stuck in `invited`
(Consiliency/agent-harness#630), and nothing obliges it to read a file in the repo. It will
neither read nor write here. This becomes real cross-agent coordination only once
Consiliency/agent-harness#630 lands.

**Why it would not have caught the mistake that prompted it:** that failure was building
into Phase 5 (SCHED) without reading the roadmap — which *already* recorded the ownership,
and Consiliency/agent-harness#354 *already* said "No SCHED runtime edits are authorized."
A claim table only helps someone who reads it first, which is the same discipline that
would have had them read the roadmap. The lever for that class is a **pre-flight
roadmap-ownership check** that fails closed, not an advisory list.

What it *is* genuinely good for: a persisted record between Claude sessions (which have no
memory of each other), and the duplicate-work class — two sessions independently
hand-cancelling the same CI runs, which happened. Cheap, tracked, survives restarts,
needs no service to be healthy.

## How to use it

**Before touching a file that the active roadmap assigns to a phase you are not executing**,
add a claim here. Before starting any work, read this file and the roadmap's per-phase
**Key files** lists — those lists are the ownership map.

Check what phase is actually running:

```sh
python3 -c "import json;print(json.load(open('.phase-loop/state.json'))['current_phase'])"
grep -n '^\*\*Key files\*\*' -A 6 specs/phase-plans-v10.md
```

Remove your claim when the work lands or is abandoned. A stale claim is worse than none —
it makes the next agent route around work that finished.

---

## Claims

### `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`

- **Claimed by:** Claude session (ad-hoc), 2026-08-23
- **Branches:** `claude/624-no-clobber-dirty-worktree` (Consiliency/agent-harness#625),
  `claude/354-worktree-gc-rebase` (Consiliency/agent-harness#626)
- **Status:** ❌ **SUPERSEDED — recommended not to merge. This is NOT a live claim.**

  This file is **Phase 5 (SCHED) lane A** in `specs/phase-plans-v10.md`. I built lane A's
  work without reading the roadmap first — the mistake this file exists to prevent. Two
  things I missed, both written down before I started:

  1. Consiliency/agent-harness#354 (2026-08-20): *"No SCHED runtime edits are authorized."*
  2. Consiliency/agent-harness#616 already contains `plans/phase-plan-v10-SCHED.md` with
     the ratifiable third framing the roadmap was waiting for — a **leased,
     generation-addressed lifecycle**.

  A 4-vendor advisory panel recommends these not merge (3–1). The designs are incompatible
  at the foundation: Consiliency/agent-harness#616 abolishes canonical-path reuse, which
  my salvage model depends on, and `IF-0-SCHED-1` forbids reconstructing a path from
  phase/branch strings — exactly what this code does. Consiliency/agent-harness#616 also
  counts *ignored and handoff state* as work; mine does not, which is a live data-loss
  path I verified and had previously dismissed.

  **SCHED lane A is NOT blocked by this claim.** Plan and execute it against
  Consiliency/agent-harness#616's design. The falsifier evidence these branches produced
  is posted on Consiliency/agent-harness#616 — nine reproduced, mutation-verified defects
  at the recreate boundary that any implementation must survive. Use the evidence; do not
  build on the code.

- **Not claimed:** `lane_scheduler.py` and `runner.py` (SCHED **lane B**) are untouched by
  this work and free.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`

- **Claimed by:** Claude session, 2026-08-23
- **Branch:** `claude/525-agy-panel-leg-permissions` (Consiliency/agent-harness#629)
- **Status:** ✅ **MERGED** (`4e45af61`) — claim released.

  **Correction to what this entry said before:** it read *"no roadmap conflict — Phase 7
  (REVIEWTRUTH) covers board degradation reporting, not leg argv."* That was judgement,
  not a check. `panel_invoker.py` IS in the **Key files** of both **Phase 6 (HARDEN)** and
  **Phase 7 (REVIEWTRUTH)**. Owned — though not barred, unlike SCHED, which carried an
  explicit prohibition.

  Leaving the correction visible rather than deleting the entry: this file's whole value
  is that it is accurate, and it recorded a wrong ownership call on day one. The same
  class of error as Consiliency/agent-harness#625, caught only because the ownership check
  was run on the *next* piece of work.

  **For REVIEWTRUTH lane D**, which owns fillable-seat/backfill composition: the merged
  change makes the agy seat fillable, which is an input to that design, not a substitute
  for it. Two facts it will need — a floor of `_MIN_USABLE_REVIEWERS = 2`
  (`governed_premerge.py:57`) never fires on a 4→3 degrade and direct `invoke_panel`
  callers get no floor at all (Consiliency/agent-harness#358); and "fillable" for agy
  currently means *unconfined*, with confinement tracked on
  Consiliency/agent-harness#525.

---

## Known concurrent work (not claims)

- **Codex agent** — branch `codex/v10-conform-plan-repair`, touching
  `phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py`.
  Phase 2 (CONFORM). No overlap with the above.
