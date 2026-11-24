# Discovery-aware JEV Drill integration

Explicit JevDrillAdapter integration is default-disabled and serial. run_loop,
launch_delegated_child and launch_harness_lane_work_unit preserve their existing
request/spec constructors and launch authority. There is no concurrent dispatcher.

discover_objective(inputs, started_at=None) calls the separately installed CLI,
validates DiscoveryResult and permits only selected_guidance/no_optional_guidance.
runner.discover_jevdrill_work_units calls the trusted ordinary planning callback
with transient returned instructions, parses its lane plan and constructs stable
task IDs. The callback owns its normal planning budget and permissions. Drill
never creates task lists. inputs_for supplies strict DiscoveryRouteInputs for
bound tasks; unbound v1 compatibility remains explicit.

The trusted callbacks verify candidate identities, enforce whole-run requested
limits, intersect configured/runtime permissions and optionally decline a
recommendation. Retaining a model requires narrowing the offered inventory or
preserving an explicit selection override; applied identities are never rewritten.
Task prompts remain immutable. Optional instructions inject once; reused prepared
prompts unwrap to their base, and execution reports guidance deactivation.

The same private ReportQueue stores only opaque discovery/task/run binding
metadata and permanent cross-producer objective tombstones. Each lifecycle
operation takes a cross-process lock before binding, preparation, final launch or
deletion. Deletion commits locally before CLI transport and survives lost replies.
Final launch rechecks installed inspect-discovery, exact reference and current
authorized catalog/revisions. Objective deletion keeps task reports independent.
Already-running work completes before a waiting deletion; bounded lock acquisition
can time out and needs caller retry. This does not promise cancellation of work.

Discover/route/report and attached notices have separate spawn-inclusive five
second logical operation budgets and 1,000,000-byte bounds. Canceled children are
killed and reaped. Recursion bypass returns before lifecycle locks/provider traffic.
One bounded queue serves all reports, sanitizes before SQLite/journal writes and
removes only matching durable accepted/duplicate event acknowledgments.

Schema/fixture digests bind the upstream HOST handoff. Native Windows argv uses
the installed JEV interpreter with -m jevdrill.cli; no unsigned launcher policy
change occurs. macOS ordinary execution stays local; JD-084 leased rejection and
Linux supervisor cleanup remain intact. Separate native receipts and independent
synthetic artifacts are software conformance evidence; no model quality,
effectiveness, savings, adoption, promotion or live-provider claim follows.

Codex usage/input capture remains Linux-only. Native macOS and Windows controls
enter launch_with_spec and record disabled/unknown provenance; Linux retains the
full observer regression suites. Imported module hashes bind each installed
companion interpreter to the collected source.

## Integration on `main` (JEVHOST)

The adapter reached `main` through the JEVHOST phase
(`plans/phase-plan-v1-jevhost-JEVHOST.md`, contract
`plans/artifacts/jevhost-v1-contract.md`), which superseded the draft
agent-harness#2071. Behaviour that differs from the draft, or that `main` added:

- **Lane waves are bypassed, and the bypass is recorded.** With
  `jevdrill_adapter` set, `run_loop` never enters the lane-wave branch, whatever
  `lane_scheduler_mode` is. The phase takes the whole-phase path through
  `launch_jevdrill`, and the event log records one `lane_scheduler` event with
  reason `jevdrill_adapter` and the requested mode. With no adapter, lane-wave
  dispatch is unchanged.
- **Review is refused on native Windows.** `launch(action="review")` raises the
  unavailable-executor error with reason `review_unsupported_on_windows` before
  any spawn. The isolated review network is Linux-only, and the Windows owned
  path cannot redact per line.
- **Codex usage on review is `unknown`.** The `--version` usage probe runs only on
  execute launches, through the owned launch seam (`launch_owned`,
  `EXECUTOR_TRUSTED`), after the admitted dependency is validated. A review launch
  starts no probe and records
  `{"capture": "disabled", "reason": "unsupported_path_or_probe"}`.
- **Redaction reaches every sink.** Seat-credential redaction runs per line before
  the usage observer, the collected output, the log and the stream.

### Installed JEV Drill tests

Tests that need an installed JEV Drill carry the per-test marker
`jevdrill_installed`. It is separate from `dotfiles_integration`.

- A marked test skips **only** when neither `JEVDRILL_TEST_CLI` nor
  `JEVDRILL_TEST_PYTHON` is set, with the fixed reason
  `jevdrill_installed: neither JEVDRILL_TEST_CLI nor JEVDRILL_TEST_PYTHON is set`.
  The required suite sets neither, so it skips them; the companion workflow's
  installed leg runs them.
- When either variable is set, `tests/jevdrill_install.py` (`resolve_install()`)
  preflights the install and **fails** on a missing or non-executable path, an
  interpreter that cannot `import jevdrill`, a CLI whose `--help` does not start
  with `usage: jevdrill`, or a CLI and interpreter from different installs. With
  one variable, the other is derived (`<python> -m jevdrill.cli`, or the `python`
  beside the CLI).
- JEV Drill's CLI has no schema or version command, so the installed leg's
  comparison of the JEV Drill checkout with `tests/fixtures/jevdrill/` carries the
  contract-pin check.

### Companion workflow and Python pairing

`.github/workflows/jevdrill-companion.yml` is a non-required workflow. On every
push to `main` and every matching pull request it runs two Linux legs over the
twelve JEV Drill test files:

- `receipt (linux, py3.12)`: neither variable set. `scripts/jevdrill_receipt.py`
  reads the junit and fails on any failure, error, skip outside its four-reason
  allowlist, missing file or missing control.
- `installed (linux, py3.12 + jev cpython-3.14)`: JEV Drill is checked out at
  `jevdrill_ref` and synced with `uv sync --locked --python cpython-3.14`; both
  variables point into that one environment, and every collected
  `jevdrill_installed` test must pass.

A `workflow_dispatch` adds the same legs on `macos-15` and `windows-2025`, and an
informational harness-on-3.14 leg that is never R3 or R6 evidence.

The harness sync command is
`uv sync --project phase-loop-runtime --group test --extra visual --locked`, and
CI tests harness pytest on Python 3.12, paired with JEV Drill on CPython 3.14.

### Dropped October evidence

The draft's `evidence/HOST-ADAPTER/*` receipts, its two execute-phase handoffs and
its detailed plan described the October run against a source tree this commit
does not have. They were not carried forward; jevdrill regenerates its own
records from the accepted commit.

## Host gaps

- When `.jevdrill/harnesses.yaml` is present, a single row must match both the
  host's `harness_id` and its `execution_target_id`. The adapter refuses an
  undeclared pair before any CLI request. If the file is absent, routing is unchanged.
- The adapter keeps retry ledgers in memory, keyed by project, workspace and task.
  The trusted request sets the budget. Recorded acceptance failures can supply
  bounded retry context, and launch admission counts attempts atomically. A
  supplied context without a ledger entry can reach routing, but prepare refuses
  it before publishing a launchable binding. The ledgers reset on adapter restart.
- Each routed prepare stamps an explicit, in-memory routing ID on
  `PromptBundle.routing_provenance`. It stays with the bundle through copies and
  field reconstruction and is excluded from rendered prompts and serialized data.
  Launch consumes the binding with that ID and refuses a routed bundle whose
  binding is unavailable.
- The runner preserves operator and policy overrides. The adapter rechecks
  readiness after the `started` report write and queues `canceled` if readiness
  has expired. Guidance deactivation carries a reason from
  `DEACTIVATION_REASONS`. CLI disconnects carry operation-specific advice, and
  report delivery keeps the queue's retry backoff.

### Item 3 run-bound report hook

Hosts using `JevDrillAdapter` can add explicit reports to the same run stream,
queue and sanitizer as the adapter's lifecycle reports.

- `run_event_identity(execution_run_id)` returns the run's `task_id`,
  `routing_decision_id`, `execution_run_id`, `source_id` and
  `next_source_sequence`.
- `enqueue_run_event(execution_run_id, payload)` assigns the event envelope,
  identity and sequence, then enqueues under the same lock as host reports.
  The payload must be non-lifecycle. A returned `queued` means the report
  entered the same durable queue as host reports. Other returned dispositions
  (`deleted`, `duplicate`, `conflict`, `overflow`) record an enqueue-time
  loss. A `duplicate` means the queue already has an identical report with
  the same event ID. The hook normally assigns a fresh ID. The hook raises
  `KeyError` for an unknown run and `ValueError` for an invalid payload.
  The hook propagates storage errors to the caller. After a storage error,
  an unconfirmed enqueue may already be stored and may still be delivered.
  Resubmitting it can duplicate its content.
- `run_report_counts(execution_run_id)` counts each returned `queued` in
  `queued` and each other returned disposition in `losses`. A raised
  exception leaves these counts unchanged.
  Later losses are counted queue-wide through `adapter.queue.status()`.

Host and hook reports share enqueue order, which follows `source_sequence`.
Delivery can be out of order. A sequence number alone does not prove enqueue,
and consumers must tolerate gaps.

The host hook is available. The downstream coverage proof for
`EC-HOST-2 / That explicit reports enter the same queue` remains JEV Drill's
responsibility.

#### Obtaining an execution run ID

During a run, call `adapter.active_execution_run_ids(task_id)` with the trusted
task ID. It returns an immutable tuple of that task's retained active run IDs
from a snapshot taken under the report lock. An ID leaves the snapshot as soon
as the executor returns, before the terminal, usage and guidance reports are
enqueued and before `launch` returns, or when its handle is evicted. A host that
reports after execution should capture the ID during the run or read it from the
launch result below.

After launch returns, read `LaunchResult.jevdrill_execution_run["execution_run_id"]`
from the routed launch result. A retained handle can still be used with the report
hook after execution. The adapter retains up to 256 of its most recently launched
run handles, and they reset on adapter restart. The report hook raises `KeyError`
for an unknown or evicted run ID.

### Item 7 spawn reserve

The transport subtracts a fixed **250 ms** from the remaining budget immediately
before spawn for operations that take `--remaining-budget-ms`. If the resulting
budget is zero or negative, the transport refuses before spawn. The parent still
uses its original deadline, with bounded cleanup to kill and reap a child. The
guarantee covers the pre-spawn reserve and parent-side enforcement. If startup
exceeds 250 ms, the child's relative deadline can extend beyond the parent's.

#### Spawn reserve tests

- (a) `tests/test_jevdrill_host_gaps.py::test_budget_reserves_spawn_time`
  checks the exact budget passed in argv. It discriminates: it fails if the
  250 ms subtraction is removed.
- (b) `tests/test_jevdrill_host_gaps.py::test_over_reserve_spawn_is_bounded_by_the_parent_deadline`
  starts a real test child and checks the original parent deadline and reaping
  after an over-reserve spawn.

The frozen
`tests/test_jevdrill_adapter.py::test_deadline_includes_prior_work_and_reaps_child`
now takes the no-spawn path because its remaining 200 ms is below the reserve.
Control (b) carries the reaping check.

#### Measurement basis

[GAPS §5 Q2](../plans/artifacts/jevhost-host-gaps-v1.md#5-rulings) records 30
CLI-like starts on Linux x86-64 under load using CPython 3.14.4. The measurement
ran from before `Popen` to the child's first output after imports. The cold
start took 79.9 ms. The warm starts had a 72.4 ms median, a 94.2 ms p95 and a
100.9 ms maximum. The 250 ms reserve is about 2.5 times that observed maximum.
