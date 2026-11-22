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
