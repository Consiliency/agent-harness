# Scratch and evidence output retention

The pytest audit scratch directory (`pl-scratch-audit-*` under `$TMPDIR`) belongs
only to its creating process. Pytest removes it after teardown, including
collection errors and handled interrupts; an exit callback covers ordinary
interpreter exit. Each xdist worker owns a separate directory. Forked children
must not delete their parent's log. SIGKILL, machine loss and an interpreter crash
can still leave scratch behind; this does not authorize deleting another live
process's temporary directory.

Evidence and review folders have a separate policy: **30 days from completion**,
with an explicit lifecycle record. Directory names, file mtimes, and a successful
review vote alone never imply permission to delete evidence. This policy manages
local output copies, not published artifacts, custody records, or Git worktrees.
Keep authoritative evidence held until its owner permits expiry or it has been
published elsewhere. Existing unmarked directories remain untouched.

## Produce managed output

Use a dedicated root whose immediate children are individual runs. The root and
run directories must belong to the current account and not be group/world
writable. Retention currently requires POSIX locking and directory operations.

The wrapper creates a fresh run directory and passes its absolute path to the
foreground producer as `PHASE_LOOP_OUTPUT_DIR`:

```sh
mkdir -p "$HOME/evidence" "$HOME/reviews"
phase-loop output-retention run --root "$HOME/reviews" --run review-20261029 \
  --finish-state published --exec sh -c \
  'produce-and-publish-review --output "$PHASE_LOOP_OUTPUT_DIR"'
```

`produce-and-publish-review` above stands for your own producer/publication
command. Use `--finish-state sealed` for a producer that seals its complete local
output; use `published` only when the command also publishes it. Choosing either
state authorizes expiry. The wrapper uses the shared launch owner in its explicit operator-executor role
and applies the runtime scratch policy. It does not grant review-seat isolation,
authentication, or qualification. Commands must run in the foreground, finish all writers,
and put only that run's disposable output in the supplied directory. Do not use
this wrapper for commands that launch background writers or return while awaiting
a native review fill. Run IDs cannot be reused.

The wrapper records `active` before starting the producer. Exit zero records the
chosen completion state. Failure or a handled interrupt records `held`; an unhandled termination (including SIGTERM) leaves `active`. Neither state
expires. Normal producer exits, including nonzero exits, sweep older eligible
siblings without changing the producer exit status. Handled exceptions record
`held` and propagate without sweeping. The launcher terminates its direct child;
before releasing a hold or completing an abandoned run, establish that all
descendant writers have stopped. `--days N` overrides
`PHASE_LOOP_OUTPUT_RETENTION_DAYS`; every sweep otherwise uses that environment
setting, falling back to 30 days.

## Existing phase-loop and HARDEN workflows

Review/native-fill workflows can span multiple invocations. HARDEN's
`build_harden_evidence.py prepare` and `seal` publish separate transactional
outputs; successful preparation is not completion. Do not change those formats
or mark a shared parent folder finished just because one file was sealed.

For these workflows, keep one dedicated directory per entire run, then explicitly
record its state. Lifecycle metadata is stored beside runs in
`.phase-loop-output-retention/`. Enrollment also creates a private
`.phase-loop-retention-token` file inside the run. Enroll before producing or
inventorying evidence; retain this token unchanged. Evidence files are not rewritten:

```sh
phase-loop output-retention mark --root "$HOME/evidence" --run harden-20261029 --state active
# Finish all preparation, seal verification and required publication first.
phase-loop output-retention mark --root "$HOME/evidence" --run harden-20261029 --state sealed
```

Mark `active` **before** resuming a completed run, or `held` for an investigation,
review HOLD or evidence preservation requirement. Manual `mark --state active`
is a cooperative declaration with no tracked producer PID; only the wrapper
records its live owner. No caller should write to a
sealed/published run without this transition. Completion time is preserved across
repeat seal/publication declarations; a new active period resets it. An explicit
hold release preserves the original completion time, so an old run may become
immediately eligible. Records bind to directory identity and the enrollment token. Keep the registry
private, and do not copy tokens into replacement directories or mutate completed
outputs during cleanup.

## Recurring cleanup

Configure roots for automatic sweeps on `phase-loop run`, `execute`, and
`advisor-board` startup:

```sh
export PHASE_LOOP_OUTPUT_ROOTS="$HOME/evidence:$HOME/reviews"
export PHASE_LOOP_OUTPUT_RETENTION_DAYS=30
```

The default is 30 days. These variables configure cleanup, not automatic enrollment
of arbitrary output. Unregistered, active, held, malformed-record and replaced
folders are preserved. A sweep error is reported on stderr without failing the
phase command. Diagnostic/dry-run commands do not trigger automatic cleanup.

Preview and apply explicitly, or put the apply commands in an operator-managed
daily timer if the runtime is used infrequently:

```sh
phase-loop output-retention prune --root "$HOME/evidence" --days 30
phase-loop output-retention prune --root "$HOME/evidence" --days 30 --apply
phase-loop output-retention prune --root "$HOME/reviews" --days 30 --apply
```

Preview returns `eligible`; apply returns `removed`. Cleanup is restricted to
registered immediate children. All lifecycle changes and sweeps serialize using
the root's lock, so other operations wait while deletion runs. Git checkouts
and other filesystem devices are refused; Linux also checks mount IDs to refuse
bind mounts. Use local, dedicated storage without mount points inside runs, and
keep permissions and lifecycle changes under the same owner.

Apply first retires the record and moves the output into a private
`.phase-loop-output-retention/.retiring-*` directory, then checks its identity
again before removal. An interrupted or incomplete retirement is preserved there
with `recovery.json`; subsequent sweeps do not retry it automatically. Inspect the
receipt and remaining output before manually recovering or disposing of it. A
failed deletion can leave partially removed output. Never restore over an existing
run directory. Missing-run records are retired as `.missing-*`; older or invalid
record formats are preserved for operator reconciliation. These small recovery
records intentionally require manual disposition.
This feature does not install a timer or retroactively enroll/delete historical
folders. It is a local storage policy, not a verification or acceptance vote.
