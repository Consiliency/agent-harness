# Detailed plan: stall-aware leg-liveness monitor (Option C)

## Task
Make advisor-panel legs time out on **lack of progress (heartbeat extinction)**, not on a blind
wall-clock. A hung leg (agy thrashing, wedged backend — pipe/PTY open, no output, no exit) currently
burns the full `_LEG_TIMEOUT_BOUNDS` deadline (up to 30 min). Fix with a **hybrid stdout-OR-CPU
heartbeat** (Option C, agreed with the maintainer).

## Research summary (verified against source)
- `panel_invoker._exec_leg` runs **codex / gemini / grok** legs via `subprocess.run(..., timeout=timeout_s)`
  — NON-streaming, wall-clock only. gemini/codex carry a post-hoc #114 transient-stall retry.
- The **claude** leg (`panel_invoker.py` ~1039+) uses `subprocess.Popen` + a PTY `select()` loop that
  streams, but its loop condition is `while time.monotonic() < deadline` — wall-clock, no stall timer.
- `_terminate_process_group` (SIGTERM→wait5→SIGKILL) already exists.
- Canonical verdict for codex/gemini/grok is the `--output-last-message` FILE, written at the END — so
  these legs emit **no incremental stdout**; stdout-silence alone is NOT a stall for them → CPU activity
  is the liveness signal.
- Byte-frozen advisor-board golden (`test_advisor_board_golden`) must stay unchanged — this is a RUNNER
  change only (no command / composition / DEFAULT_LEG_MODELS change).

## Changes

### `src/phase_loop_runtime/panel_invoker.py` (modify)
- **`_run_leg_with_liveness(command, cwd, env, deadline, stall_threshold, *, pty=False) -> (rc, output, reason)`** — add — the unified stall-aware runner:
  - `Popen` the command (pipe stdout+stderr, or PTY when `pty=True` for the claude TUI leg).
  - Loop until process exit / stall / deadline. Poll output via `select()` on a short interval; each chunk
    → append + reset `last_heartbeat`.
  - Every ~5–10s sample the process GROUP's CPU (`utime+stime` from `/proc/<pid>/stat` for the pid AND its
    descendants — codex/grok spawn children); if total advanced → reset `last_heartbeat`.
  - **Stall** iff stdout silent AND CPU flat for `stall_threshold` (default **120s**) → `_terminate_process_group`
    + return `(rc or 1, output, "stalled")` (fail closed; nothing to nudge for a silent+idle print-mode leg).
  - **Deadline** (`monotonic > deadline`) → hard backstop → terminate + `(rc or 1, output, "deadline")`.
  - Normal exit → `(proc.returncode, output, "exit")`.
- **codex / gemini / grok branches of `_exec_leg`** — modify — replace `subprocess.run(...)` with
  `_run_leg_with_liveness(...)`; keep the `--output-last-message` file read for the verdict; keep the #114
  transient-stall retry (wrap the call, same retry predicate on the combined output/reason).
- **claude PTY leg (~1039)** — modify — route its select-loop through the same liveness logic (add the
  stdout-or-CPU stall-timer; keep PTY EOF (#48) fast-return + transcript-salvage semantics).

### `src/phase_loop_runtime/_proc_cpu.py` (create, small)
- `group_cpu_ticks(pid) -> int` — sum `utime+stime` for `pid` and its descendants from `/proc`. Returns 0
  if `/proc` is unavailable (non-Linux) so the runner degrades to stdout-only heartbeat (still correct: a
  streaming leg heartbeats on stdout; a silent-and-idle one is genuinely dead).

## Documentation impact
- `CHANGELOG.md` (repo root) — Unreleased entry: stall-aware leg-liveness monitor (kill on
  heartbeat extinction, wall-clock backstop retained).

## Dependencies & order
1. `_proc_cpu.group_cpu_ticks` first (pure, testable).
2. `_run_leg_with_liveness` next.
3. Route the three subprocess.run legs + the claude PTY loop through it.

## Verification (prove the behavior — the whole point)
- `sleep 600` (no output, no CPU) → killed in ~`stall_threshold`, elapsed << deadline. **assert**.
- CPU-active-but-silent (`python -c "while True: pass"`) → SURVIVES past `stall_threshold` (CPU heartbeat),
  dies only at the deadline backstop. **assert both.**
- Streaming (`while true; do echo .; sleep 1; done`) → survives (stdout heartbeat).
- Real codex/grok/gemini/claude legs still return verdicts (smoke, not in CI if network-bound).
- `python -m pytest tests/ -q` green; advisor-board golden UNCHANGED; skills-bundle/docs-audit guards green.

## Acceptance criteria
- [ ] A no-output+no-CPU process is terminated in ~`stall_threshold`, not at the wall-clock deadline.
- [ ] A CPU-active silent process survives to the deadline (not false-killed).
- [ ] codex/gemini/grok verdict extraction (`--output-last-message`) + #114 retry preserved.
- [ ] claude PTY path preserved (EOF fast-return, salvage) with the stall-timer added.
- [ ] advisor-board golden byte-unchanged; full suite green.

## Execution Policy
- execute: effort=high, reason=delicate PTY/subprocess + /proc CPU sampling on the load-bearing review path.
