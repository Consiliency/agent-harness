# Detailed plan: expose the grok leg through advisor-board `available_panel_legs()`

## Task
Consiliency/agent-harness#171 (request #1): `available_panel_legs()` returns only
`('codex','gemini','claude')` — the 4th vendor lane `grok` (grok-4.5) is never exposed, so
`invoke_panel("", available_panel_legs(), ...)` can never include grok and a caller whose
gemini/agy leg is down has no supported way to reach a 4th independent vendor except a
fragile hand-rolled grok CLI. Expose grok through `available_panel_legs()`, staying
**availability-aware** (grok appears only when its CLI is actually installed).

Out of scope (do NOT fold in): request #2 (the agy `-p -` empty-prompt fix — landed
separately) and request #3 (skill guidance that hand-rolled CLI legs must reference the
staged artifact, never inline) — the latter is noted under Documentation impact.

## Research summary
One Explore pass over `phase_loop_runtime/panel_invoker.py` (citations from it):
- `available_panel_legs(probe=None)` (`:317-324`) is the whole change site:
  `check = probe or (lambda cli: shutil.which(cli) is not None); return tuple(leg for leg
  in PANEL_LEGS if check(_LEG_CLI[leg]))`. grok is excluded **only** because it is absent
  from the iterated `PANEL_LEGS` — its probe never runs. The default probe is PATH-only
  (`shutil.which`), no auth.
- Everything else grok needs **already exists**: `_LEG_CLI` (`:76`) maps
  `"grok":"grok"`; `DEFAULT_LEG_MODELS` (`:88-93`) has `grok→"grok-4.5"`;
  `_LEG_TIMEOUT_BOUNDS` (`:169`) and the grok spawn path (`:2381-2422`, headless `grok -p`
  + read-only `--tools` allow-list, `--reasoning-effort` via `render_seat_invocation` —
  fixed in Consiliency/agent-harness#222/#225) all carry grok; the 4-vendor
  `_HOMEBREW_LANES` (`:2883`) already includes grok. `advisor_board/registries.py:206-225`
  registers grok with the identical `shutil.which("grok")` probe whose docstring says it
  "mirrors `panel_invoker.available_panel_legs`".
- **`PANEL_LEGS` (`:67`) is byte-frozen** at `("codex","gemini","claude")` and pinned by
  goldens: `tests/test_panel_invoker.py:75`, `tests/test_advisor_board_backcompat.py:39-40`
  (CANONICAL_LEG_ORDER / DEFAULT_BOARD families), and ~15 assertions in
  `tests/test_advisor_board_golden.py`. It **must not** change. But `available_panel_legs`
  itself has **no** 3-tuple golden — its only test (`test_panel_invoker.py:23-27`) injects a
  probe and asserts the returned set — so returning grok when `which("grok")` succeeds is
  safe. `invoke_panel` is byte-frozen and just spawns whatever legs it is handed; callers
  (`governed_review.py:241`, `runner.py:8865,8926`) pass the result straight through, and
  their tests patch `available_panel_legs` with their own tuples, so they are insulated.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- New module const near `PANEL_LEGS`/`_LEG_CLI` (`:67-76`) — add
  `_AVAILABLE_PANEL_LEGS: tuple[str, ...] = PANEL_LEGS + ("grok",)` — the ordered
  vendor set `available_panel_legs` considers (codex, gemini, claude, grok). Reason: expose
  grok WITHOUT mutating the byte-frozen `PANEL_LEGS` keystone. A one-line comment states
  this is the availability list, distinct from the frozen 3-vendor `PANEL_LEGS`.
- `available_panel_legs` (`:317-324`) — modify — iterate `_AVAILABLE_PANEL_LEGS` instead of
  `PANEL_LEGS` (one word change to the comprehension source). Reason: grok is now probed
  and included when `shutil.which("grok")` succeeds; the availability-aware default probe
  and per-leg `_LEG_CLI` mapping are unchanged, so degradation (N=4 target, floor 3) is
  preserved and a host without the grok CLI still returns the exact 3-tuple.
- **Frozen-vocabulary confirmation:** `PANEL_LEGS` (`:67`), `DEFAULT_LEG_MODELS`, and every
  golden the backcompat/golden suites pin are LEFT BYTE-IDENTICAL — grok is added ONLY to
  the new `_AVAILABLE_PANEL_LEGS` list that `available_panel_legs` iterates. No frozen
  contract token is modified.

### `phase-loop-runtime/tests/test_panel_invoker.py` (modify)
- Add `test_available_panel_legs_includes_grok_when_present` — inject `probe=lambda cli:
  True` → assert the result contains `"grok"` and equals `("codex","gemini","claude","grok")`
  (all four, in order); inject `probe=lambda cli: cli != "grok"` → assert `"grok"` is
  absent (availability-aware); and assert `PANEL_LEGS == ("codex","gemini","claude")` is
  UNCHANGED (grok never entered the frozen tuple). Reuse the existing probe-injection
  pattern at `:23-27`.

## Documentation impact
- `CHANGELOG.md` — add — `available_panel_legs()` now includes `grok` when the grok CLI is
  installed, so the documented panel entry point reaches all four vendors (and backfills a
  down vendor onto grok) without a hand-rolled CLI leg.
- **Skill docs — FOLLOW-UP (flagged, not this plan's code deliverable):** ~9 advisor-board
  skill docs describe `available_panel_legs()` / the manual-grok-backfill workaround —
  editable sources `phase-loop-skills/advisor-board/SKILL.md` (+ `_overrides/{gemini,claude,
  opencode}`) and `skills-src/{claude,codex,gemini,opencode}/*-advisor-board/SKILL.md`; the
  `phase_loop_runtime/src/phase_loop_runtime/skills_bundle/*` copies are GENERATED (regen via
  the skills-bundle tooling; neutral base is codex — do NOT hand-edit the bundle). Updating
  that guidance (drop the manual backfill; note grok auto-included) + issue #171 request #3
  (hand-rolled CLI legs must reference the staged artifact, never inline) is a bounded
  docs-only follow-up, kept OUT of this code change to preserve scope + a clean regen.

## Dependencies & order
None — a single self-contained function change plus its test. No migration, no consumer
change (callers already forward the tuple; `invoke_panel` and the grok spawn path already
handle a grok leg end-to-end).

## Execution Policy
- execute: effort=low, reason=single-function availability-list extension + one probe-injected
  unit test; all grok plumbing (CLI map, model, timeout, spawn) already exists.

## Verification
```bash
cd phase-loop-runtime
# new + existing available_panel_legs behavior, and the frozen goldens intact
PYTHONPATH=src:tests python -m pytest tests/test_panel_invoker.py \
  tests/test_advisor_board_backcompat.py tests/test_advisor_board_golden.py -q
# direct behavioral check (probe injection; no grok CLI needed)
PYTHONPATH=src python -c "from phase_loop_runtime.panel_invoker import available_panel_legs, PANEL_LEGS; \
assert available_panel_legs(lambda c: True) == ('codex','gemini','claude','grok'); \
assert 'grok' not in available_panel_legs(lambda c: c!='grok'); \
assert PANEL_LEGS == ('codex','gemini','claude'); print('ok')"
# governed/runner suites that consume the entry point (insulated, must stay green)
PYTHONPATH=src:tests python -m pytest tests/ -q -k "governed_review or panel_invoker or advisor_board"
```
Edge cases: (a) grok CLI present → all 4 returned in order; (b) grok CLI absent (this host)
→ exact 3-tuple, unchanged; (c) a custom probe excluding grok → grok dropped; (d) the
frozen `PANEL_LEGS` + golden suites unchanged.

## Acceptance criteria
- [ ] `available_panel_legs(probe=lambda cli: True) == ("codex","gemini","claude","grok")`.
- [ ] `"grok" not in available_panel_legs(probe=lambda cli: cli != "grok")` (availability-aware).
- [ ] `PANEL_LEGS == ("codex","gemini","claude")` unchanged, and
      `test_advisor_board_backcompat.py` + `test_advisor_board_golden.py` stay green.
- [ ] `test_available_panel_legs_includes_grok_when_present` passes; the governed_review /
      runner suites that consume the entry point stay green.
