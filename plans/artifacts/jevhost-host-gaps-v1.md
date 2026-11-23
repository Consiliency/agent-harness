# JEVHOST host gaps v1: item findings and the generic host seam

Frozen planning artifact for `plans/amendments/jevhost-JEVHOST-host-gaps.md`. It is
read-only during execution. A change needs a reviewed repin in that amendment and in its
`plans/manifest.json` row. Sections are cited as GAPS §N.

## §0 Inputs

| Input | Pin |
| --- | --- |
| agent-harness base | `main` at `424f4c9d893ea7bd7fbd17da82b8a73c9e9bcd02`. All file:line evidence below is at this commit. |
| JEVHOST contract | `plans/artifacts/jevhost-v1-contract.md`, sha256 `1fa957afc8f7b3a324a8f048695b3d2ebf1009336a1d49407d33dfc1b36f4e1d` (unchanged by this amendment) |
| JEV clause source | `Consiliency/jevdrill` at `8c0df4bc25eae708e2e0d6a578eda745832bf166`: `plans/phase-plan-v1-HOST.md` (EC-HOST-1, EC-HOST-2 and EC-HOST-4 tables, "Other scope notes"), `evidence/HOST/coverage.json` (the nine `not_covered` clauses), `specs/phase-plans-v1.md` (HOST scope notes, JD-084) |
| Owner decisions | 2026-11-23, relayed by JEV-Drill via Spec Root: cover the nine gaps with discriminating producer tests, and EC-HOST-3 stays synthetic-only. Scope change, same day: build only GENERAL items here; JEV-SPECIFIC items are JEV-owned against a generic host interface. |

Each item below maps one-to-one to a `not_covered` clause of the JEV coverage file. The
clause text is JEV's, cited by its EC-HOST ID, and is not restated here.

## §1 Classification and status

**GENERAL** means good practice for any host integration. **JEV-SPECIFIC** means it only
has meaning in JEV Drill's setup.

| # | Item (JEV clause) | Class | Reason | Status at the base |
| --- | --- | --- | --- | --- |
| 1 | Bounded `retry_context` on acceptance failure (EC-HOST-1) | GENERAL | Any router needs the failed run and the remaining attempt and time budget to reroute safely. | **missing** |
| 2 | Deactivation reports the actual host limitation (EC-HOST-1) | GENERAL | Any integration that injects guidance should say why the guidance ended. | **partial** |
| 3 | Explicit reports enter the same queue as hook reports (EC-HOST-2) | JEV-SPECIFIC | The hook/explicit split and its queue are JEV's reporting protocol. | **partial** |
| 4 | Outage/disconnect resolution advice (EC-HOST-2) | GENERAL | Any out-of-process integration fails, and the operator needs a supported next step. | **partial** |
| 5 | A launch that keeps an operator-set model (EC-HOST-4) | GENERAL | No integration may replace an operator or policy override. | **implemented, unexercised** |
| 6 | Readiness recheck immediately before launch (scope note) | GENERAL | Any routed decision can go stale between routing and launch. | **partial** |
| 7 | Budget passed after host spawn time (scope note) | GENERAL | Any budgeted child CLI must not outlive the host's deadline. | **missing** |
| 8 | Ordinary macOS execution stays local (JD-084) | JEV-SPECIFIC | It is JEV's platform amendment. The launcher behaviour already exists and is public. | **implemented, unexercised** |
| 9 | No forwarding without a declaration (scope note) | GENERAL | An integration must not send work for a harness identity the project never declared. | **partial** |

**Evidence** (paths under `phase-loop-runtime/`):

1. `src/phase_loop_runtime/jevdrill_adapter.py:444-445` and `:607` only read
   `request["retry_context"]`, which `inputs_for` supplies. No code builds one. The runner
   has no acceptance-failure signal to any integration (`runner.py:3588`,
   `_finalize_phase_launch`).
2. `guidance_deactivated` is emitted at `jevdrill_adapter.py:647-648` with
   `reason: None` (`:548-549`), and `sanitize_report` forces every lifecycle reason to
   `None` (`:300-301`). The control `tests/test_jevdrill_adapter.py:575` asserts only that
   the event exists.
3. `ReportQueue` accepts `evaluation` and `host_choice` payloads
   (`jevdrill_adapter.py:302-313`). Only the internal `_report` (`:539-553`) enqueues, and
   there is no explicit-report entry point bound to a run.
4. Transport failures raise a bare `OSError` or `TimeoutError`
   (`jevdrill_adapter.py:118`, `:164-168`, `:188`, `:193`). The post-launch delivery
   failure records `{"status": "delivery_failed"}` with no advice (`:650-653`). The
   control `tests/test_jevdrill_adapter.py:444` asserts the disposition only.
5. An override that differs from the plan is refused (`jevdrill_adapter.py:484-486`), and
   a matching one is kept (`:519-520`). The only control,
   `tests/test_jevdrill_adapter.py:244`, exercises the refusal. Nothing outside the
   adapter checks that an integration preserved an override (`runner.py:3404-3405`,
   `:5525`, `:6236` take `request.model_selection` as returned).
6. The final recheck exists (`jevdrill_adapter.py:576-584`), and
   `tests/test_jevdrill_adapter.py:265` controls expiry between `prepare` and `launch`. But
   the readiness test (`:578`) runs **before** the `verify_candidate` and
   `limits_enforced` callbacks (`:579-580`), which may be slow live probes. So it is not
   the last check before `launch(` (`:596`).
7. `remaining` is computed at `jevdrill_adapter.py:116` and passed as
   `--remaining-budget-ms` (`:121`) before `subprocess.Popen` (`:134`). JEV's CLI anchors
   its deadline at its own start (`src/jevdrill/cli.py`, `min(5000, remaining_budget_ms)`
   from `_STARTED`), so its deadline overshoots the host's by the spawn time.
8. `launcher.py:2981-2988` rejects only `sys.platform == "darwin"` **with**
   `lease_authority`. The control `tests/test_jevdrill_adapter.py:652` covers the leased
   rejection. No test runs an unleased darwin launch.
9. When `.jevdrill/harnesses.yaml` exists but has no row for the envelope's
   `(harness_id, execution_target_id)`, `jevdrill_adapter.py:429-433` narrows the
   declared capabilities and routes to the empty set, and still sends the `route` request
   (`:459`). When the file is absent (`:30-31`), routing proceeds undeclared. That is v1
   compatibility, `docs/jevdrill-integration.md` lines 12-13, and this amendment leaves it
   unchanged (§5 Q1).

## §2 The generic host seam (new module `host_integration.py`)

This is the owner's "generic host interface". It is host-neutral: it names no JEV schema,
path or CLI flag, and it does no IO, spawn or `ctypes`. The JEV adapter consumes it.

- `RETRY_FAILURE_CLASSES = ("infrastructure", "quality")`.
- `build_retry_context(*, prior_execution_run_id, prior_routing_decision_id, failure_class, attempts_used, max_attempts, started_monotonic, total_deadline_ms, now_monotonic) -> dict | None`.
  - It returns `None` when `attempts_used >= max_attempts` (exhausted).
  - Otherwise it returns exactly these keys: `failure_class`,
    `failure_summary = "host_acceptance_failed:" + failure_class` (a closed code, no free
    text), the two prior IDs, `remaining_attempts = max_attempts - attempts_used`,
    `remaining_time_ms = max(0, total_deadline_ms - elapsed_ms)` and
    `remaining_spend = None`. The host has no verified spend measurement.
  - It raises `ValueError` for a class outside `RETRY_FAILURE_CLASSES`.
- `record_acceptance_failure(integration, execution_run, *, failure_class) -> bool`. It
  calls `integration.record_acceptance_failure(execution_run, failure_class=...)` when
  the integration defines it. It returns whether it did.
- `DEACTIVATION_REASONS = ("guidance_scoped_to_task_prompt", "executor_unavailable", "executor_identity_mismatch", "launch_canceled")`.
- `deactivation_reason(*, available, identity_mismatch, interrupted) -> str`. It returns
  the first that applies, in this order: `executor_unavailable`,
  `executor_identity_mismatch`, `launch_canceled`. Otherwise it returns
  `guidance_scoped_to_task_prompt`: the host can scope guidance to one immutable task
  prompt only, so the guidance ends with the task.
- `DISCONNECT_RESOLUTION_ADVICE`, a tuple of exactly three supported steps:
  1. "Check that the configured integration CLI starts and answers --help."
  2. "Queued reports are kept and retried on the next flush."
  3. "Run without the integration to launch unrouted."
- `annotate_disconnect(exc) -> exc`. It sets `exc.resolution_advice =
  DISCONNECT_RESOLUTION_ADVICE` and returns the **same** exception object, so callers keep
  their exception types.
- `OVERRIDE_DEFAULT_SOURCES(executor) -> frozenset`, which is `{"default", executor + "_default"}`.
- `build_host_request(integration, builder, *, mode, dry_run, **kwargs)`. This is the
  generic form of `build_jevdrill_request`. When `kwargs["model_selection"].source` is
  not a default source, the selection that `integration.prepare` returns must equal the
  original in `model`, `effort` and `source`. Otherwise it raises
  `HostOverrideViolation(ValueError)` before `builder` runs. With `integration is None`
  it is exactly `builder(**kwargs)`.

`build_jevdrill_request` (`jevdrill_adapter.py:681`) stays, unchanged. It is used by tests
and is not an R5 name, but it is kept.

**Where each GENERAL item lives.**

| # | Generic seam | Stays in the JEV adapter, and why |
| --- | --- | --- |
| 1 | builder, failure classes, runner hook | the per-task failure record, and the mapping into JEV's `RetryContext` schema |
| 2 | vocabulary and mapping | emitting it in JEV's lifecycle payload, and the sanitizer's allowlist |
| 4 | advice constant and annotation | where the JEV transport fails, and the notice dict sent to `notice_sink` |
| 5 | override guard in `build_host_request`, used by the runner | nothing new (`:484-486` and `:519-520` stay) |
| 6 | none | The ordering is internal to the adapter's `_launch`. It moves to the seam only when a second integration exists. |
| 7 | none | `--remaining-budget-ms` is JEV's CLI contract, and a one-line helper would not pay for itself |
| 9 | none | the declaration file and its format are JEV's (`.jevdrill/harnesses.yaml`) |

## §3 Behaviour and discriminating tests (GENERAL items)

Each test fails at the §0 base, for the reason given.

| # | Behaviour (owning module) | Test (file::name) | Asserts | Why it fails without the behaviour |
| --- | --- | --- | --- | --- |
| 1a | `build_retry_context` (`host_integration.py`) | `tests/test_host_integration.py::test_retry_context_is_bounded_and_closed` | exact keys; `remaining_attempts` = max − used; time is clamped at 0; `None` when exhausted; the summary is the closed code; an unknown class raises | the module does not exist |
| 1b | `_finalize_phase_launch` calls `record_acceptance_failure` when an integration is set, the result carries `jevdrill_execution_run`, and the phase is classified `blocked` or `unknown`. The class is `infrastructure` when the result is unavailable, timed out or stalled, else `quality` (`runner.py`). | `tests/test_host_integration_runner.py::test_failed_acceptance_is_recorded_on_the_integration` | a recording fake integration on a planned phase whose routed launch fails acceptance receives one call, with that run and class; a passing phase records none | no runner call site exists |
| 1c | The adapter keeps a bounded per-task failure record (at most 256 tasks, oldest evicted). For that task, `_prepare` puts `build_retry_context(...)` into `request["retry_context"]` when `inputs_for` supplied `None`. It refuses with `JevDrillUnavailable("Retry attempts are exhausted")` before `route` when exhausted. It refuses a supplied context whose prior IDs differ from the record (`jevdrill_adapter.py`). | `tests/test_jevdrill_host_gaps.py::test_acceptance_failure_builds_bounded_retry_context` | prepare, launch, record, prepare: the second `route` payload's `retry_context` names the first run's `execution_run_id` and `routing_decision_id`, with `remaining_attempts` = `max_attempts` − 1; after the budget, no `route` call | at the base the second payload's `retry_context` is `None` |
| 2 | `sanitize_report` keeps a lifecycle `reason` only when it is in `DEACTIVATION_REASONS`, else `None`. `guidance_deactivated` carries `deactivation_reason(...)` (`jevdrill_adapter.py`, using `host_integration.py`). | `tests/test_jevdrill_host_gaps.py::test_deactivation_reports_the_host_limitation[...]`, parametrized over completed, unavailable, identity mismatch and canceled | the flushed `guidance_deactivated` report's `reason` equals the mapped code; a free-text reason put into a lifecycle report is stored as `None` | at the base every reason is `None` |
| 4 | Transport failures in `prepare`, `discover_objective` and `flush` are annotated with `annotate_disconnect`. A `{"kind": "transport_disposition", "status": "disconnected", "resolution_advice": [...]}` notice is emitted before the re-raise. `delivery_failed` warnings carry the same advice. A non-ready decision's `details.capability_mismatches[*].resolution_advice` is copied onto `JevDrillUnavailable.resolution_advice` (`jevdrill_adapter.py`). | `tests/test_jevdrill_host_gaps.py::test_disconnect_carries_supported_resolution_advice` | an unspawnable CLI argv: the raised exception's type is unchanged and its `resolution_advice == DISCONNECT_RESOLUTION_ADVICE`; the notice sink got the same tuple; a flush outage warning carries it; a capability-mismatch decision's advice is surfaced verbatim | no advice field exists at the base |
| 5a | `build_host_request` override guard (`host_integration.py`). The runner's three `build_jevdrill_request` sites (`runner.py:3388`, `:5509`, `:6221`) call it (`runner.py`). | `tests/test_host_integration.py::test_override_replacing_integration_is_refused` and `tests/test_host_integration_runner.py::test_runner_refuses_an_integration_that_replaces_an_override` | a fake integration that rewrites a `user_override` selection: `HostOverrideViolation`, and the builder and launch are never called | at the base the runner takes the returned selection as is |
| 5b | (no change) | `tests/test_jevdrill_host_gaps.py::test_operator_model_is_kept_through_launch` | with a `user_override` selection and an inventory narrowed by `inputs_for` to that model, the spec launches with the operator model; `source` stays `user_override`; `applied_plan_id` is set; started and completed reports are queued | It fails if `:519-520` replaced the selection (`source` would be `jevdrill`). It is a regression control. |
| 6 | Reorder `_launch`: run the identity, `verify_candidate` and `limits_enforced` checks first. Then evaluate the freshness and readiness rows last, with nothing between them and `_report(binding, "started")` and `launch(` except the codex kwargs (`jevdrill_adapter.py`). | `tests/test_jevdrill_host_gaps.py::test_readiness_is_rechecked_after_the_final_callbacks` | `verify_candidate` returns True on its launch-time call, but advances the patched clock past `valid_until`: no launch and no report | at the base readiness is read before the callback, so the launch starts |
| 7 | `JevDrillTransport.call` reserves `SPAWN_ALLOWANCE_MS = 100`. The argv budget is `int((deadline - now) * 1000) - SPAWN_ALLOWANCE_MS`, computed immediately before `Popen`. If it is ≤ 0, it raises `TimeoutError("... before spawn")` and does not spawn. The host's own wait deadline is unchanged (`jevdrill_adapter.py`). | `tests/test_jevdrill_host_gaps.py::test_budget_accounts_for_spawn_time` | with a fake monotonic clock and a recording `Popen` seam that advances the clock by 50 ms: `budget_ms / 1000 <= deadline - clock_after_spawn`, and the budget equals the formula exactly | at the base budget = deadline − clock_before_spawn, which exceeds it by the spawn time |
| 9 | When a declaration file exists and has no row for the envelope's identity, `_prepare` raises `JevDrillUnavailable("Harness identity is not declared")` before `route` (`jevdrill_adapter.py`). | `tests/test_jevdrill_host_gaps.py::test_undeclared_harness_identity_is_never_forwarded` | a declaration naming another harness: the error is raised and no `route` call is recorded; the declared-row case still routes | at the base `route` is called with no candidates |

Every test is synthetic: loopback or a fake CLI, no provider, model or live JEV call.
EC-HOST-3 stays synthetic-only.

## §4 Not in scope (JEV-owned)

| # | Why JEV owns it | Generic hook JEV needs from agent-harness |
| --- | --- | --- |
| 3 | The hook-versus-explicit report split is JEV's protocol. `ReportQueue` is already public (`jevdrill_queue.ReportQueue`, an R5 name), and its `enqueue` runs the same sanitizer as hook reports. | **A post-launch run handle.** Today `LaunchResult.jevdrill_execution_run` (`launcher.py:360`) gives `execution_run_id` and `task_id`, but not `routing_decision_id`, the envelope scope or the next `source_sequence`, which an explicit report needs to join the run's stream. agent-harness builds this hook only when JEV files a request for it. Not in these lanes. |
| 8 | JD-084 is JEV's platform amendment. The behaviour exists (`launcher.py:2981`) and needs no change. | None. `launcher.launch(..., lease_authority=None)` is public. JEV's native macOS runner can exercise it without patching. |

## §5 Open questions (non-blocking; the default applies)

- **Q1.** Should routing refuse when `.jevdrill/harnesses.yaml` is absent? **Default: no.**
  v1 compatibility (`docs/jevdrill-integration.md` lines 12-13) stays, and item 9 covers
  a declaration file that is present.
- **Q2.** Should `SPAWN_ALLOWANCE_MS` be measured rather than fixed? **Default: fixed
  100 ms.** The host deadline still bounds the child, so a slow spawn costs JEV work but
  never host safety.

## §6 JEVHOST contract check

No item needs a change to the frozen JEVHOST contract. These sentences were checked, and
the amendment stays inside them:

- §6 [C7]: "The collected node IDs of the six JEV Drill files and the four LEARN files
  equal the list in `tests/data/jevdrill_test_names.json`." All new tests are in new files
  outside the twelve, so the list and the companion receipt are unchanged.
- §10: "a resolution needs to change a file another lane owns, a file outside the phase's
  key files (the §13 inventory files are key files), ...". This governs the replay's
  resolutions. Here each lane's owned-file list stands in for the key files, and the other
  §10 stop rules apply unchanged.
- §13: "A row the table does not cover stops the lane for a ruling, not a guess." No new
  launch, IO or `ctypes` primitive is added. `host_integration.py` does no IO. If
  `tests/test_seat_reference_inventory.py` or `tests/test_agent_cli_scratch_inventory_1147.py`
  moves, the lane stops.
- §7 (R5): no R5 name is renamed or removed.
