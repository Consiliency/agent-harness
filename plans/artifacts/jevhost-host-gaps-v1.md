# JEVHOST host gaps v1: item findings and the generic host seam

Frozen planning artifact for `plans/amendments/jevhost-JEVHOST-host-gaps.md`. It is
read-only during execution. A change needs a reviewed repin in that amendment and in its
`plans/manifest.json` row. Sections are cited as GAPS §N.

**Revision 2 (2026-11-23).** This revision applies the plan review of agent-harness#2124
(REQUEST CHANGES) and the coordinator's rulings on Q1 and Q2. Each change is tagged:
- [F1] the retry authority and the per-run decision record (§2, §3.1);
- [F2] disconnect advice that preserves queue backoff (§3.4);
- [F3] readiness after the last blocking write, and the spawn-reserve wording (§3.6, §3.7);
- [F4] SL-8's baseline expectations and the entered runner proofs (§3.5, §3.0);
- [F5] authority, key files and continuity evidence (§6);
- [P] placement: only the host-neutral parts go to `host_integration.py` (§2);
- [Q1] and [Q2] are ruled (§5).

## §0 Inputs

| Input | Pin |
| --- | --- |
| agent-harness base | `main` at `424f4c9d893ea7bd7fbd17da82b8a73c9e9bcd02`. All file:line evidence is at this commit. |
| JEVHOST contract | `plans/artifacts/jevhost-v1-contract.md`, sha256 `1fa957afc8f7b3a324a8f048695b3d2ebf1009336a1d49407d33dfc1b36f4e1d` (unchanged) |
| JEV clause source | `Consiliency/jevdrill` at `8c0df4bc25eae708e2e0d6a578eda745832bf166`: `evidence/HOST/coverage.json` (the nine `not_covered` keys of §1), `plans/phase-plan-v1-HOST.md`, `specs/phase-plans-v1.md`, `src/jevdrill/cli.py` |
| RetryContext schema | `phase-loop-runtime/tests/fixtures/jevdrill/RouteInputs.json` `$defs.RetryContext` at the base. `remaining_time_ms` and `remaining_attempts` are integers with minimum 0. |
| Spawn reserve | `SPAWN_ALLOWANCE_MS = 250`, measured as in §5 Q2 |
| Owner decisions | 2026-11-23, relayed by JEV-Drill via Spec Root: cover the nine gaps with discriminating producer tests; EC-HOST-3 stays synthetic-only. Scope change, same day: GENERAL items only. Coordinator rulings on Q1 and Q2, same day (§5). |

## §1 Classification and status

The clause keys are the exact `criterion` / `clause` pairs of the pinned coverage file.

| # | Coverage key | Class | Reason | Status at the base |
| --- | --- | --- | --- | --- |
| 1 | `EC-HOST-1` / "Acceptance failures supply bounded rerouting context: the host half" | GENERAL | Any router needs the failed run and the remaining attempt and time budget to reroute safely. | **missing** |
| 2 | `EC-HOST-1` / "Deactivates at task end, reporting host limitations" | GENERAL | Any integration that injects guidance should say why the guidance ended. | **partial** |
| 3 | `EC-HOST-2` / "That explicit reports enter the same queue" | JEV-SPECIFIC | The explicit-report schema, the queue protocol and the downstream proof are JEV's. | **partial** (open gap, §4) |
| 4 | `EC-HOST-2` / "Disconnects include supported resolution advice" | GENERAL | Any out-of-process integration fails, and the operator needs a supported next step. | **partial** |
| 5 | `EC-HOST-4` / "The harness may retain its current model: a launch that keeps it" | GENERAL | No integration may replace an operator or policy override. | **implemented in the adapter, unexercised; no generic guard** |
| 6 | `scope` / "Scope note: the readiness recheck before launch" | GENERAL | Any routed decision can go stale between routing and launch. | **partial** |
| 7 | `scope` / "Scope note: the budget passed after host spawn time" | GENERAL | Any budgeted child CLI should not be told it has more time than the host allows. | **missing** |
| 8 | `scope` / "Scope note: ordinary macOS execution staying local" | JEV-SPECIFIC | It is the JD-084 downstream obligation. The general launcher behaviour already exists. | **implemented, no native control** |
| 9 | `scope` / "Scope note: the absence of silent forwarding" | GENERAL | An integration must not send work for a harness identity the project's declaration omits. | **partial** |

**Evidence** (paths under `phase-loop-runtime/`):

1. `jevdrill_adapter.py:444-445` and `:607` only read the `retry_context` that
   `inputs_for` supplies. The routing-decision ID lives in the pending binding, which is
   popped at launch (`:524-532`, `:559-562`, `:603-608`). `last_decision` is shared
   across tasks. `runner.py:3588` (`_finalize_phase_launch`) makes no integration call.
2. `jevdrill_adapter.py:300-301` erases every lifecycle reason. `:548-549` and
   `:647-648` emit `guidance_deactivated` with `reason: None`.
   `tests/test_jevdrill_adapter.py:575` checks only that the event exists.
3. `jevdrill_queue.py:234-261` exposes `enqueue` with the configured sanitizer, and
   `jevdrill_adapter.py:302-313` accepts the payload shapes. The envelope and sequence are
   owned by the internal `_report` (`:539-553`), and no run-bound reporting API exists.
4. Transport failures raise a bare `OSError` or `TimeoutError` (`jevdrill_adapter.py:118`,
   `:134`, `:164-193`). The queue consumes those errors from its send callback and commits
   backoff (`jevdrill_queue.py:275-302`), so a real report-delivery outage is a silent
   `retry`. `:650-653` and `:661-670` give a launch warning with no advice.
5. `jevdrill_adapter.py:484-486` refuses a differing override and `:519-520` keeps a
   matching one. `tests/test_jevdrill_adapter.py:244` covers only the refusal. The runner
   accepts the returned selection as is (`runner.py:3404-3405`; request sites `:3388`,
   `:5509`, `:6221`).
6. `jevdrill_adapter.py:576-584` rechecks freshness, but before the `verify_candidate`
   and `limits_enforced` callbacks (`:579-580`) and before `_report("started")`
   (`:585-596`). That call runs the sanitizer and a SQLite write
   (`jevdrill_queue.py:234-261`).
7. The budget is computed at `jevdrill_adapter.py:116`, before argv construction and
   `Popen` (`:119-134`). JEV's CLI anchors its deadline at its own start
   (`src/jevdrill/cli.py:81`, `:112`). The parent deadline bounds the wait (`:159-198`).
8. `launcher.py:2981-2988` refuses leased Darwin only. The leased controls are
   `tests/test_phase_loop_launcher.py:1866` and `:1940-1944`, and
   `tests/test_jevdrill_adapter.py:652-657`. The Darwin case in
   `tests/test_jevdrill_input.py:124-144` stubs the launcher.
9. `jevdrill_adapter.py:425-459` reads the optional declaration. On an unmatched row it
   narrows to zero candidates and still calls `route`. The notice call (`:412`) and the
   linked inspection (`:414`) contact the CLI before the declaration is read.

## §2 The generic seam (`host_integration.py`) [P]

The module is host-neutral. It names no JEV schema, path or CLI flag, and it does no IO,
spawn or `ctypes`. Everything else stays in the adapter.

- `ACCEPTANCE_FAILURE_CLASSES = ("infrastructure", "quality")`.
- `RetryBudget`: a frozen dataclass with `max_attempts: int`, `total_deadline_ms: int`
  and `first_started_ns: int` (a `time.monotonic_ns()` value).
  - `remaining(attempts_used, now_ns)` returns `(remaining_attempts, remaining_time_ms)`:
    - `remaining_attempts = max(0, max_attempts - attempts_used)`;
    - `remaining_time_ms = max(0, (total_deadline_ms * 1_000_000 - (now_ns - first_started_ns)) // 1_000_000)`,
      an integer by floor division.
  - `exhausted(attempts_used, now_ns)` is true when either value is 0.
  - `tighten(other)` returns a budget with the smaller cap, the smaller deadline and the
    earlier start.
- `AcceptanceObserver`, a `typing.Protocol` with one method,
  `record_acceptance_outcome(execution_run_id: str, *, passed: bool, failure_class: str | None) -> None`.
  This is the frozen semantics of IF-0-JEVHOST-5. SL-7 tests against it with a fake, so
  it never imports an unlanded adapter.
- `notify_acceptance(integration, execution_run_id, *, passed, failure_class) -> bool`.
  - It calls the observer when the integration implements it, and returns whether it did.
  - It validates `failure_class`: `None` when passed, else one of the classes.
  - It catches no exception. The runner owns error handling (§3.1).
- `DEACTIVATION_REASONS`, a closed vocabulary: `guidance_scoped_to_task_prompt`,
  `executor_unavailable`, `executor_identity_mismatch`, `launch_canceled`,
  `launch_aborted`.
- `deactivation_reason(*, result_returned, available, identity_mismatch, interrupted) -> str`.
  The first rule that matches wins:
  1. `launch_aborted` if the launch raised before returning a result;
  2. `executor_unavailable`;
  3. `executor_identity_mismatch`;
  4. `launch_canceled`;
  5. otherwise `guidance_scoped_to_task_prompt`.
- `disconnect_advice(operation) -> tuple[str, ...]` covers `operation in {"route", "report"}`.
  - **`route`** (any pre-launch call):
    1. "Check that the configured integration CLI starts and answers --help."
    2. "Retry the launch once the integration is reachable, or run without the integration; an unrouted launch remains subject to the ordinary launch authority."
  - **`report`**:
    1. "Check that the configured integration CLI starts and answers --help."
    2. "The report stays queued and is retried after its backoff on a later flush, unless it expires, overflows the queue or its task is deleted."
- `annotate_disconnect(exc, operation) -> exc` sets `exc.resolution_advice` and returns
  the same object.
- `build_host_request(integration, builder, *, mode, dry_run, **kwargs)`.
  - Before `prepare`, it snapshots `(model, effort, source)` of
    `kwargs["model_selection"]` as an immutable tuple of the original field values.
  - When that `source` is not in `{"default", executor + "_default"}`, the returned
    selection's three fields must equal the snapshot. Otherwise it raises
    `HostOverrideViolation(ValueError)` before `builder` runs. A comparison of
    identically mutated objects therefore cannot pass.
  - With `integration is None` it is exactly `builder(**kwargs)`.

**What stays in the adapter**, and why:
- the per-task retry ledger and its mapping into JEV's `RetryContext`;
- the lifecycle emission and the sanitizer allowlist;
- where transport failures occur, and the notice dict;
- capability-mismatch advice copying, an adapter mapping for an adjacent clause that is
  already covered downstream;
- the readiness ordering (6);
- the argv budget (7);
- the declaration check (9).

`build_jevdrill_request` (`jevdrill_adapter.py:681`) stays unchanged.

## §3 Behaviour and discriminating tests

### §3.0 Baseline rule [F4]

- Every new test runs once against the §0 base before any implementation. The lane
  records each outcome by node ID.
- Every test **must fail on the base with its named assertion**, except:
  - the 5b retained-model regression, which must **pass** on the base, and must fail
    under a recorded mutation that overwrites `selection.source` at
    `jevdrill_adapter.py:519-520`;
  - the positive controls marked "passes on base".
- Before closing, each lane checks that every named test collects
  (`--collect-only -q`) and executes in its verify command (`-rA`).

### §3.1 Item 1 [F1]

- **Budget owner.** It is the trusted host request that `inputs_for` returns:
  `hard_constraints.max_attempts` and `hard_constraints.total_deadline_ms`.
- **Retry ledger** (adapter). It is keyed by `(project_id, workspace_id, task_id)` and
  created at the task's first routed `prepare`. It records:
  - a `RetryBudget`, whose `first_started_ns` is that prepare's start;
  - `attempts`, a list of `{execution_run_id, routing_decision_id, outcome}`.
  - A later prepare can only `tighten` the budget, never widen it. The start never moves.
- **Run-to-decision binding.** In `_launch`, after the pending binding is popped and
  before `launch(`, the adapter appends `{run_id, details.routing_decision_id,
  "launched"}` to that task's ledger, and indexes `run_id` to its ledger key. So every
  launched run keeps its exact decision, scoped by project, workspace and task.
  `last_decision` is never used for this.
- **`record_acceptance_outcome(run_id, *, passed, failure_class)`** (adapter):
  - an unknown or evicted run ID is ignored and emits one `acceptance_unknown_run` notice;
  - a duplicate call for the same run is idempotent: the first outcome wins;
  - `passed=True` closes the task and deletes its ledger entry;
  - otherwise the attempt's outcome becomes `failure_class`.
- **Construction.** At a later `prepare` for a task whose latest attempt failed:
  - `attempts_used` is the number of launched attempts;
  - if `budget.exhausted(...)`, it raises `JevDrillUnavailable("Retry budget is exhausted")`
    before any CLI contact;
  - otherwise it builds `{failure_class, failure_summary: "host_acceptance_failed:<class>",
    prior_execution_run_id, prior_routing_decision_id, remaining_attempts,
    remaining_time_ms, remaining_spend: None}` from the latest failed attempt.
- **Supplied context.** If `inputs_for` supplies a non-`None` `retry_context`, it is
  checked for both supplied and generated contexts against the ledger. It is refused, with
  no route, if:
  - there is no failed attempt;
  - a prior ID differs;
  - the class differs;
  - either bound exceeds the host's value;
  - the budget is exhausted.

  When accepted, the host sends its own generated context. A supplied context with no
  ledger entry is refused.
- **Bound on the ledger.** It holds at most 256 open tasks. A first prepare for a 257th
  open task is refused (`"Retry ledger is full"`). Open entries are never evicted, so a
  budget cannot be reset by eviction. Closed entries are deleted. A process restart
  loses the ledger. A retry is then routed as a first attempt, and JEV's own attempt
  check (`application.py:1201-1219` at the pin) still bounds it. SL-9 states this.
- **Runner verdict** (`_finalize_phase_launch`). There is one helper,
  `_report_acceptance(prep, result, verdict)`. It is called only on paths after an
  entered launch whose result carries `jevdrill_execution_run`:

  | Path | Verdict |
  | --- | --- |
  | `reduction_blocker` (`:3609`) | none: not judged on the run |
  | `result.failed` (`:3704`) and unavailable, timed-out or stalled results | `infrastructure` |
  | a zero-exit run whose post-launch gate or verification sets blocked (`:3993`) | `quality` |
  | `launch_contract_blocker` (`:3766`) | `quality` if it judges the run's own output, else none. SL-7 records which it is, with evidence. If it is ambiguous, stop. |
  | phase reaches its success status | `passed=True` |
  | any other blocked or unknown state | none |

  Any exception from `notify_acceptance` is caught. It appends one
  `jevdrill_acceptance_hook_failed` event and never changes the classification.

**Tests.**

| Row | Test | Asserts | Base outcome |
| --- | --- | --- | --- |
| 1a | `tests/test_host_integration.py::test_retry_budget_arithmetic_and_exhaustion` | positive elapsed arithmetic; the exact boundary (`remaining_time_ms` reaches 0 at the deadline, and floor rounding to an int); exhaustion by attempts and by time separately; `tighten`; an unknown class raises | fails: the module does not exist |
| 1b | `tests/test_host_integration_runner.py::test_acceptance_verdicts_reach_the_observer[...]` | parametrized: nonzero exit gives `infrastructure`; zero exit plus a failing gate gives `quality`; success gives `passed`; `reduction_blocker` gives no call; the observer raises and the classification is unchanged with one event. Each case asserts the launch was entered and the literal class. | fails: no call site |
| 1c | `tests/test_jevdrill_host_gaps.py::test_acceptance_failure_builds_bounded_retry_context` | with a controlled `monotonic_ns`: two independent tasks; prepare, launch, failure, prepare. The second `route` payload names both prior IDs of **that** task's run, `remaining_attempts = max - 1`, and the exact `remaining_time_ms`. A duplicate failure call does not double-count. After exhaustion there is no `route`. | fails: `retry_context` is `None` |
| 1d | `tests/test_jevdrill_host_gaps.py::test_supplied_retry_context_cannot_widen_or_bypass` | widened attempts, widened time, mismatched IDs, an exhausted budget and a no-ledger supply are each refused with no `route` | fails: the base forwards them |

### §3.2 Item 2

`sanitize_report` keeps a lifecycle `reason` only when `event_type ==
"guidance_deactivated"` and the reason is in `DEACTIVATION_REASONS`. Every other lifecycle
reason is `None`. `_launch` computes `deactivation_reason(...)` in its `finally`,
including when `launch` raised.

**Test.** `tests/test_jevdrill_host_gaps.py::test_deactivation_reports_the_host_limitation[...]`
covers five cases: completed, unavailable, identity mismatch, canceled and raised. Each
uses injected guidance. The test flushes until empty, selects the delivered event whose
`event_type` is `guidance_deactivated`, and asserts the literal code. A free-text reason
on a `started` event is `None`. **Base:** fails for the literal codes. The redaction part
alone would pass, so it is not the discriminator.

### §3.3 Item 3: JEV-owned (§4)

### §3.4 Item 4 [F2]

- **Pre-launch calls** (`_notices`, `inspect-discovery`, `route` and `discover` in
  `prepare` and `discover_objective`).
  - An `OSError` or `TimeoutError` from `transport.call` is annotated with
    `disconnect_advice("route")`.
  - One notice `{"kind": "transport_disposition", "status": "disconnected", "operation":
    "route", "resolution_advice": [...]}` is emitted.
  - The **same** exception object is re-raised.
- **Report delivery** (`flush`). The adapter's `send` closure wraps its two transport
  calls. On `OSError` or `TimeoutError` it annotates with `disconnect_advice("report")`,
  sets a per-flush flag and **re-raises into the queue**. The queue then commits its
  backoff exactly as today (`jevdrill_queue.py:285-302`). After `deliver_one` returns
  `retry` with the flag set, `flush` emits one notice with `operation: "report"` and
  returns `retry`. `flush` does not raise for a disconnect.
- **Launch.** `_launch`'s outer `except Exception` warning (`delivery_failed`) stays,
  without advice, for non-transport errors: sanitizer `ValueError`, queue corruption. The
  executor result is still returned.

**Tests.**

| Test | Asserts | Base outcome |
| --- | --- | --- |
| `test_jevdrill_host_gaps.py::test_route_disconnect_carries_advice[prepare\|discover]` | the real `JevDrillTransport` with an unspawnable argv, entered independently through `prepare` and `discover_objective`; the raised object is the original type (`FileNotFoundError`); `resolution_advice == disconnect_advice("route")`; exactly one notice | fails: no advice |
| `test_jevdrill_host_gaps.py::test_report_disconnect_keeps_backoff_and_advises` | seeds a pending report, then runs the real `flush` over the real `send` with the unspawnable transport; the result is `retry`; the row persists with `attempts == 1` and `retry_at` in the future (read from the queue file); exactly one `report` notice; then `adapter.launch` with the same transport returns the executor result unchanged | fails: no notice; the base retries silently |
| `test_jevdrill_host_gaps.py::test_non_transport_delivery_errors_stay_distinct` | a sanitizer `ValueError` during launch reporting gives `delivery_failed` with no `resolution_advice` | passes on base (control) |

### §3.5 Item 5 [F4]

| Row | Test | Asserts | Base outcome |
| --- | --- | --- | --- |
| 5a | `tests/test_host_integration.py::test_build_host_request_refuses_override_changes[model\|effort\|source\|in_place]` | a fake integration changes each field independently, and an in-place mutation of the passed object; `HostOverrideViolation`; the builder is not called | fails: the module does not exist |
| 5a | `tests/test_host_integration.py::test_build_host_request_passes_preserved_override_and_default_routing` | a preserved override passes, and a default selection may be replaced | fails: the module does not exist |
| 5a | `tests/test_host_integration_runner.py::test_runner_refuses_an_integration_that_replaces_an_override[main\|delegated\|lane]` | the real `run_loop`, `launch_delegated_child` and `launch_harness_lane_work_unit` constructors with a host-neutral fake integration, with the builder and launcher observed; the launcher is never called | fails: the base launches |
| 5b | `tests/test_jevdrill_host_gaps.py::test_operator_model_is_kept_through_launch` | a `user_override` selection and an inventory narrowed by `inputs_for`; the launcher is reached once with the operator model and effort; `source` stays `user_override`; `applied_plan_id` is set; the queued `started` and `completed` events carry that launch's run ID | **passes on base**, and fails under the §3.0 mutation |

### §3.6 Item 6 [F3]

Order in `_launch`:
1. The existing early freshness and readiness check, unchanged. It keeps
   `tests/test_jevdrill_adapter.py:265` true.
2. Identity, `verify_candidate` and `limits_enforced`.
3. `_report("started")`.
4. **A final freshness and readiness recheck**, followed directly by `launch(`, with
   only the codex kwargs between them.

If the final recheck fails after `started` was persisted:
- the adapter enqueues the lifecycle `canceled` for that run;
- if guidance was injected, it also enqueues `guidance_deactivated` with
  `launch_canceled`;
- no usage report is sent;
- it raises `JevDrillUnavailable("...not enforceable")`.

**Tests.**

| Test | Asserts | Base outcome |
| --- | --- | --- |
| `test_jevdrill_host_gaps.py::test_readiness_expiring_in_a_final_callback_refuses_launch` | readiness is valid at the early check (asserted); `verify_candidate` returns True on its launch-time call (asserted reached) but advances the patched clock past `valid_until`; no launch; the queue holds `started` then `canceled` for the run | fails: the base launches |
| `test_jevdrill_host_gaps.py::test_readiness_expiring_during_the_started_write_refuses_launch` | the queue's `enqueue` is wrapped to advance the clock after writing `started`; same assertions | fails: the base launches |
| `test_jevdrill_host_gaps.py::test_fresh_launch_reports_started_before_dispatch` | the launcher is called once, after `started` is queued | passes on base (control) |

### §3.7 Item 7 [F3]

- **Behaviour.** `JevDrillTransport.call` builds the argv, then computes
  `budget_ms = int((deadline - time.monotonic()) * 1000) - SPAWN_ALLOWANCE_MS`. This is
  the last statement before `Popen`, after validation and argv construction, and only
  for the commands that take the flag.
  - If `budget_ms <= 0`, it raises `TimeoutError("... before spawn")` with no spawn.
  - The parent's wait deadline is unchanged, and post-spawn cleanup kills and reaps
    exactly as today.
  - `delete` keeps its argv shape, with no budget flag.
- **What it guarantees.** A pre-spawn reserve plus parent-side enforcement after spawn.
  It does not guarantee that the child's deadline falls before the parent's when the
  spawn takes longer than the reserve. That would need a JEV protocol change: a shared
  absolute deadline or a post-start budget handshake. This amendment does not request one.

**Tests.**

| Test | Asserts | Base outcome |
| --- | --- | --- |
| `test_jevdrill_host_gaps.py::test_budget_reserves_spawn_time` | a fake monotonic clock and a recording `Popen` seam; the argv budget equals the formula exactly, and `budget_ms / 1000 + SPAWN_ALLOWANCE_MS / 1000 <= deadline - clock_at_budget` | fails: the base budget has no reserve |
| `test_jevdrill_host_gaps.py::test_near_zero_budget_never_spawns` | remaining ≤ the reserve: `TimeoutError` "before spawn", and the `Popen` seam is not called | fails: the base spawns |
| `test_jevdrill_host_gaps.py::test_over_reserve_spawn_is_bounded_by_the_parent_deadline` | a real fake child that sleeps past the deadline, with the real timed wait: `TimeoutError` within the original deadline plus a 1 s cleanup bound; the child is reaped | passes on base (control) |
| `test_jevdrill_host_gaps.py::test_delete_argv_has_no_budget_flag` | the exact `delete` argv | passes on base (control) |

The frozen `tests/test_jevdrill_adapter.py::test_deadline_includes_prior_work_and_reaps_child`
uses 200 ms remaining, which is now under the reserve. It still passes, with
`TimeoutError` in under 2 s, but through the no-spawn branch. Its reaping meaning is
carried by `test_over_reserve_spawn_is_bounded_by_the_parent_deadline`. SL-9 states this.

### §3.8 Item 9 [Q1]

- **Boundary.** "Forwarding" means **any** CLI request dispatched for that identity. The
  declaration load and match move to the top of `_prepare`, before `_notices`, the linked
  inspection and `route`.
- **Refusal.** When `.jevdrill/harnesses.yaml` **exists** and no row matches both
  `harness_id` and `execution_target_id`, the adapter raises
  `JevDrillUnavailable("Harness identity is not declared")`, with zero transport calls.
- **Unchanged.** An absent file keeps today's routing. Unbound v1 discovery compatibility
  (`docs/jevdrill-integration.md` lines 12-13) is a separate rule and is unchanged.

**Tests.**

| Test | Asserts | Base outcome |
| --- | --- | --- |
| `test_jevdrill_host_gaps.py::test_undeclared_identity_makes_no_cli_request[harness\|target\|both]` | a fixture with `repo`, a valid declaration and a ready candidate; the harness ID, the target ID or both are varied independently; every transport call is recorded, and none is made | fails: the base calls `notices` and `route` |
| `test_jevdrill_host_gaps.py::test_declared_identity_and_absent_file_still_route` | a matching row routes; no file routes | passes on base (control) |

All tests are synthetic: loopback or a fake CLI, with no provider, model or live JEV call.

## §4 Not in scope (JEV-owned)

| # | Status | Generic hook JEV would need |
| --- | --- | --- |
| 3 | The coverage gap stays **open** until JEV supplies its proof. | **One opaque run-bound enqueue capability.** It is issued per launched run. It binds to the same `ReportQueue` and sanitizer. It allocates event identity and `source_sequence` under the adapter's sequencing, so a single producer stream stays ordered. It respects tombstones, retry and idempotency. It states its lifetime across restart. An independent `source_id` would need its own sequencing contract instead. **Deferred** until JEV files a request. Not in these lanes. |
| 8 | The general behaviour (ordinary local execution, no implicit cross-machine forwarding) is implemented at `launcher.py:2981-2988`. | None. `launcher.launch(..., lease_authority=None)` is public. JEV's native macOS runner can make the unleased JD-084 control without patching. |

## §5 Rulings

- **Q1 (ruled).** When the declaration file is absent, routing stays as today. The adapter
  refuses only when the file exists without a row for this identity (§3.8). A mandatory
  declaration would need a separate owner decision on compatibility.
- **Q2 (ruled).** The reserve is a fixed constant, set from measured startup times. There
  is no per-process learning and no extra probe.
  - **Method.** On a Linux x86-64 development host, under a one-minute load of about 12
    on 24 CPUs, with CPython 3.14.4 run as `python -I -c`, the parent records
    `time.monotonic()` before `Popen`. The child prints its own `time.monotonic()` as its
    first output after imports. CLOCK_MONOTONIC is shared across processes on Linux.
    There were 30 runs per case; the first run is reported as cold, the rest as warm.
  - **Results** (ms):

    | Case | Cold | Warm median | Warm p95 | Warm max |
    | --- | --- | --- | --- | --- |
    | bare interpreter | 7.6 | 7.9 | 9.3 | 9.8 |
    | CLI-like imports (`json`, `argparse`, `sqlite3`, `hashlib`, `uuid`, `jsonschema`, `yaml`) | 79.9 | 72.4 | 94.2 | 100.9 |

    `Popen` itself returned within 4.7 ms.
  - **Constant.** `SPAWN_ALLOWANCE_MS = 250`. That is about 2.5 times the worst observed
    CLI-like start, which leaves margin for hosted macOS and Windows runners. Their
    interpreter start is slower, and they were not measured here.
  - The constant is a pinned input. Changing it needs a GAPS repin with a new
    measurement.

## §6 Authority, key files and continuity [F5]

- **Key files.** This amendment amends the roadmap's Phase 1 **Key files**
  (`specs/phase-plans-jevhost-v1.md`) to add these paths:
  - `phase-loop-runtime/src/phase_loop_runtime/host_integration.py`;
  - `phase-loop-runtime/tests/test_host_integration.py`;
  - `phase-loop-runtime/tests/test_host_integration_runner.py`;
  - `phase-loop-runtime/tests/test_jevdrill_host_gaps.py`.

  It repins `roadmap_sha256` in the JEVHOST plan and in the amendment. JEVHOST §10 then
  applies unchanged.
- **Inventories** (JEVHOST §13). SL-4's ownership covered the completed replay. For
  this amendment, the reviewed supersession is as follows:
  - **SL-9** is the reducer for inventory **runs**. On the combined tree it runs all five
    §13 tests: `test_seat_reference_inventory.py`,
    `test_agent_cli_scratch_inventory_1147.py`, `test_seat_resource_caps.py`,
    `test_seat_launch_helpers_trusted.py` and `test_gate_fail_open_visibility.py`.
  - **No lane may edit an inventory file.** If one moves, including a row moved by a split
    or relocated site at the same count, the lane stops. A GAPS repin then rules the row
    under §13's role table.
  - The retained sites keep `host-helper` (JEV CLI spawn), `host-io`, and
    `operator-out-of-scope` (`git check-ignore`).
- **The twelve frozen test files** and `tests/data/jevdrill_test_names.json` are
  read-only. SL-9 runs them, with `test_jevdrill_selection.py` and
  `test_jevdrill_companion_workflow.py`. An edit to any of them is a stop and a repin.
  - §6 [C7] says "The collected node IDs of the six JEV Drill files and the four LEARN
    files equal the list in `tests/data/jevdrill_test_names.json`." The new tests live
    in new files, so this holds.
  - §7 (R5): no R5 name is renamed or removed.
- **Continuity evidence.** The landed evidence is from agent-harness#2086. The follow-up
  reruns the checks named here:

  | ID | Landed evidence | Follow-up rerun |
  | --- | --- | --- |
  | EC-JEVHOST-1 | the merged R1 paths and `uv sync --locked` | `test_jevdrill_selection.py`, and the required sync in CI |
  | EC-JEVHOST-2 | the contract copies and `digests.json` | untouched by this amendment; `test_jevdrill_receipt.py`'s compare-contract cases |
  | EC-JEVHOST-3 | S1 to S6 per JEVHOST §4, with their landed controls | `test_jevdrill_launch_merge.py`, `test_jevdrill_runner_lanes.py`, `test_launch_audit_inventory.py`, and SL-7's no-integration paths. A single lane-wave test does not prove EC-JEVHOST-3. |
  | EC-JEVHOST-4 | the companion receipt and installed legs | the receipt leg runs on the implementation PR, because the path filter covers `jevdrill_adapter.py` and `runner.py` |
  | EC-JEVHOST-5 | the selection and LEARN rules | `test_jevdrill_selection.py` |
  | EC-JEVHOST-6 | the R5 imports | `test_jevdrill_selection.py::test_every_r5_name_imports` |
  | EC-JEVHOST-7 | the sync command and the pairing | `test_jevdrill_companion_workflow.py`; no workflow is changed |
  | EC-JEVHOST-8 | `gitleaks` and the disclosure grep | the required `gitleaks` check, and SL-9's grep over the diff |

- **External dispatch.** If Gate A or a companion dispatch is used, SL-9 records the run
  links and the head's tree hash after the dispatch.
