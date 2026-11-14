# Lane execution

The runner defaults to `concurrent` lane scheduling with a ceiling of four.
It selects machine-verified disjoint ready lanes, prepares isolated worktrees
and launch specs for the whole wave, then starts a bounded worker pool. All
children finish before output transport or the next wave. Dependent waves see
HEAD plus accepted preceding lane output, including additions and deletions;
the parent's index and unrelated dirty files are preserved.

The normal action routing, governed planning, resolved executor/model/effort,
release approval and authentication checks precede lane execution. Planning
and review retain their existing routes. Phase scheduling still defaults off.
Each child reports lane completion; only the parent runs combined phase
verification and ordinary phase closeout. Child lanes must not publish or
perform phase closeout. Heavy verification remains a single admitted run;
lane count is not a test-worker allowance.

## Controls

- `--lane-scheduler off` or `PHASE_LOOP_LANE_SCHEDULER=off` selects coarse
  execution. An explicit flag takes precedence over the environment.
- `--max-parallel-lanes 1` also selects coarse execution. The flag overrides
  `PHASE_LOOP_MAX_PARALLEL_LANES`; the default is four. Values below one and
  malformed values are rejected.
- `serialized` retains its legacy record-only behavior; use `off` for real
  serial execution. Dry-run lane previews create no lane work-unit records.
- `WORKTREE_ROOT` controls the worktree directory. Team hosts otherwise use
  `~/workspace/worktrees`; other hosts keep the existing location resolver.

Selection without disjoint ownership, conflicting executor pins, unavailable
worktrees/specs, and capacity below two produce reason-coded serial fallback
before launch. After any child starts, failures preserve recovery evidence and
block instead of launching a second coarse writer.

## Capacity policy boundary

The isolated memory helper reads host MemAvailable and every finite ancestor
cgroup limit. With an explicit `PHASE_LOOP_LANE_MEMORY_BUDGET_BYTES` it clamps
the ceiling by the smallest remaining-byte reading divided by that budget.
Readings, budget, effective count and reason are recorded. Unreadable capacity
retains the configured ceiling with `capacity_unknown`; this does not authorize
heavy work with unknown headroom.

The default is a configurable, provisional 2 GiB per-lane policy budget, not
measured child usage or a seat limit. Recalibrate it from the first real lane
observation. Raw cgroup remaining memory counts cache as used; cache credit and
adaptive pressure scheduling remain deferred. No live capacity qualification is
claimed. Both final and per-lane launch events retain the capacity readings.

## Recovery and verification

Lane attempts are bound to plan content, phase, base HEAD and attempt identity.
Transport intent is durably recorded before apply; completion follows apply.
Uncertain running, refused, or incomplete transport records produce
`lane_recovery_required` with `human_required=false`. Worktrees and branches
remain evidence. Automatic relaunch and double application are prohibited.
Changing plans or selecting `off` does not erase uncertainty. With fully
transported output, `off` uses ordinary dirty-worktree closeout checks.

Only parsed, trusted `complete` closeouts with passed verification, successful
child exit and no blocker, parse error or human requirement permit transport.
Each transported path must match that lane's own patterns. Combined-tree
verification runs after all accepted transports and before phase closeout;
failed verification blocks closeout. Existing manual/commit/push authority,
governed review and publication controls remain in effect.

### Deliberate recovery

A recovery event identifies `journal_paths` and legacy `work_unit_ids`. Inspect
the referenced records and preserved worktrees first; confirm all prior writers
have exited. Under the existing ownership authority, salvage and integrate or
explicitly discard their output, checking whether transport already applied.
Archive the affected journal outside `lane-attempts` only after reconciliation;
retain its original bytes and the recovery decision. For legacy work-unit IDs,
retain the state snapshot, then use `state.write_work_unit_state` with the
identified record transitioned to `superseded` only after the same reconciliation;
record the disposition in its closeout summary. This is deliberate maintainer
recovery, not an automatic retry. Never delete evidence or
edit an uncertain record to pretend success, and never automatically relaunch.
A known refused closeout still requires this deliberate disposition, but is not
evidence that transport began.
