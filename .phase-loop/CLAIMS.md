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
- **Status:** ⚠️ **CONFLICTS WITH ROADMAP — disposition pending**

  This file is **Phase 5 (SCHED) lane A** in `specs/phase-plans-v10.md`. The roadmap
  states lane A is **BLOCKED**: the Consiliency/agent-harness#354 design fork was paneled
  twice, options (a)/(b)/(c) were rejected 3/3, and *"a third framing is required before
  lane A starts."*

  I built lane A's work without reading the roadmap first. That was the mistake this file
  exists to prevent. Consiliency/agent-harness#625 additionally cannot satisfy **EC-SCHED-0**
  (tests must land first, paneled and RED, with the implementation PR not modifying them) —
  its commits interleave tests and implementation and rewrite an existing test.

  Disposition is with an advisory panel. **Do not plan or execute SCHED lane A until this
  claim is resolved** — the work already exists on those two branches and would be
  duplicated.

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
