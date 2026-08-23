# Active file claims

Cross-agent coordination surface. Two agents work this repo concurrently (a Codex agent
executing the roadmap, and Claude sessions doing ad-hoc work) and there is currently **no
live channel between them** — the Codex agent's message-board membership is stuck in
`invited`, so it can neither be reached nor report its own state (see
Consiliency/agent-harness#630).

Until that is fixed, this file is the coordination mechanism. It is deliberately crude:
plain text in the repo, so it survives either agent restarting and needs nothing to be
healthy.

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
- **Status:** open, no roadmap conflict — Phase 7 (REVIEWTRUTH) covers board
  *degradation reporting*, not leg argv. Narrow change: adds the headless permission flag
  the gemini/agy leg needs to function at all (Consiliency/agent-harness#525).

---

## Known concurrent work (not claims)

- **Codex agent** — branch `codex/v10-conform-plan-repair`, touching
  `phase-loop-runtime/src/phase_loop_runtime/conformance/outside_agent_conform_evidence.py`.
  Phase 2 (CONFORM). No overlap with the above.
