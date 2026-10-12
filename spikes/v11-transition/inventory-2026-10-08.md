# v10 → v11 transition inventory (snapshot, 2026-10-08)

This is a point-in-time record of the work in flight when `specs/phase-plans-v11.md` was drafted.
It is not updated as work moves. The ledger (`plans/manifest.json`) and the v11 phase plans are
the live record.

## Method

Every agent-harness worktree on the two development hosts in use (258 in total) was listed with
its branch, uncommitted-file count, commits not on `origin/main`, and whether the branch is on
`origin`. Each branch was joined to its pull request. Squash merges make commit comparison
unreliable, so the pull-request state decides what is finished. Pushed branches with no pull
request and no worktree were checked separately. Nothing was changed, merged or reclaimed.

| Class | Count |
|---|---|
| Open or draft pull request | 14 |
| Commits but no pull request | 58 (35 local-only) |
| Uncommitted changes only | 31 |
| Pull request merged or closed; worktree left over; or empty | 155 |

## Work and its v11 phase

| Work | State | v11 phase |
|---|---|---|
| agent-harness#1264 (SL-5 evidence), agent-harness#1351 (plan authority) | Draft | HARDEN |
| Branches `codex/v10-harden-sl5-r21-final`, `-r21-prep`, `-r20-seal-drift`, `-squashed-20261007`, `codex/v10-harden-first-parent-repair-20261006`, `backup/claw-harden-r18-sol-bd530210` | Pushed 2026-10-08 as backups; no pull request | HARDEN |
| Branch `claude/1078-panel-sl1` (38 commits, PANEL SL-1) | Pushed 2026-10-08 as backup; no pull request | PANEL |
| agent-harness#1168 (SL-1b), agent-harness#1199 (vendor-seat roster plan) | Open / draft | PANEL |
| Branch `codex/v10-execfind-sl4-20260925` (28 commits) | Pushed 2026-10-08 as backup; no pull request | EXECFIND |
| agent-harness#1203 (plan), agent-harness#1208 (SL-0) | Open / draft, idle since 2026-10-01 | RATIFY |
| agent-harness#1000 (evidence-loss policy) | Draft | RUNTIME |
| agent-harness#986 (Codex native review), agent-harness#1284 (structured replies), agent-harness#851 (diagnostics retention) | Draft | REVIEWTRUTH |
| agent-harness#383 (crash-resume seam plan) | Draft, idle since 2026-09 | RESIDUAL |
| Branch `claude/claude-print-route-plan` | Unpublished, active | Lands before PANELSPLIT or rebases onto it |
| agent-harness#1323, agent-harness#1325, agent-harness#1328, agent-harness#1350 | Open | Land before v11 is frozen |

## Open issues routed to phases

| Phase | Issues |
|---|---|
| TESTLOOP | agent-harness#766, agent-harness#1335, agent-harness#854, agent-harness#428, agent-harness#1344, agent-harness#1345 |
| LOOPFIX | agent-harness#831, agent-harness#1305, agent-harness#1346, agent-harness#1354 |
| HARDEN | agent-harness#808, agent-harness#1003 |
| LEGLIFE | agent-harness#730, agent-harness#734, agent-harness#926, agent-harness#856, agent-harness#857 |
| PANEL | agent-harness#934 |
| RESIDUAL | agent-harness#789, agent-harness#820, agent-harness#833, agent-harness#979 |
| REFLOOP | agent-harness#1304 |

Older local branches tied to these issues (September 2026) are not revived as branches. The
owning phase's plan reads them as prior art.

## Not part of v11

- jevdrill integration and native-Windows work: uncommitted, a separate initiative.
- One host's primary checkout sits on a merged branch with a large staged change set of
  unknown origin. It needs its owner to identify it before anything is reclaimed.
- 84 pushed branches with no pull request, mostly August review rounds and scratch CI
  dispatches marked "never merge".

## v10 phases found not ready to close

- **SCHED.** A frozen test fails on `main`: commit `da9502b3` gave
  `_launch_with_lease_supervisor` new required arguments. The two branches EC-SCHED-7 protects
  were deleted from `origin` with no recorded decision.
- **RUNTIME.** EC-RUNTIME-0's tests-first receipt is lost (agent-harness#720), and EC-RUNTIME-2's
  live reconciliation is partial.
- **PRESROUTE.** Every goal is met in code. Two frozen-test edits (`e2dff674`, `da9502b3`) lack
  `sl0_repairs` records, which also strands PANEL SL-1's pending authorization.
- **HARDEN.** EC-HARDEN-5 cannot be met as written under the per-seat jail design.
- **EXECFIND.** Its content receipt fails since agent-harness#1292 edited a frozen test.
