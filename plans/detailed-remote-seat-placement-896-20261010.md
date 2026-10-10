---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1246, agent-harness#1162, agent-harness#1165, agent-harness#1245, agent-harness#1222, agent-harness#1166, agent-harness#1253, agent-harness#1170]
amends: [plans/detailed-remote-sandbox-placement-896-20260929.md, plans/detailed-e2b-cloud-backend-896-20260929.md, plans/detailed-1244-seat-route-resolver-20261004.md]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_ladder_model.py tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_seat_notices.py tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_panel_leg_status_detail_1096.py tests/test_launchspec_golden.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: the execution driver for non-local placement — admission, lease journal, reaper, runtime receipts (agent-harness#896, plan 1b, brought up to date)

## Task

A shared host that launches a review board runs every seat itself, because only the
placement seam exists (agent-harness#1246). The maintainer ruled on 2026-10-10 that seats
move to a self-hosted compute host **over SSH first**, with the cloud backend as overflow
afterwards.

This plan is the first unit of that work: the runtime's execution driver. It is
vendor-neutral, it is proven with fake backends, and it changes no behaviour:
`_NONLOCAL_EXECUTION_DRIVER` stays false and the launch site is not touched. A second unit
with no behaviour change, the launch and credential factoring, is planned beside it in
`plans/detailed-seat-launch-factoring-896-20261010.md`. The two do not depend on each
other.

**The follow-on plans**, each written and reviewed on its own, in this order. None exists
yet; each is held to the contract in this document.

| Follow-on plan | What it does | Driver flag |
|---|---|---|
| SSH backend and `placement qualify` | An `ssh` backend, its compute-host entry point, and the command that qualifies a compute host, with a null workload | off |
| Reconnect | A started workload survives a dropped connection and is resumed by the run that launched it (ruling Q1) | off |
| Placed Claude seat | The jailed Claude seat runs on the compute host | **turns on** |
| Codex and grok under a leased seat uid | Those seats get a subordinate kernel uid on the compute host (ruling RD3, legs (ii)), then are placed | on |

**What is expected to leave the launching host**, on a four-seat board of Claude, codex,
grok and Gemini: nothing until the placed-Claude-seat plan lands; then the Claude seat, 1 of
4; then, with the last plan, codex and grok as well, 3 of 4, for a user on ordinary
subscription logins. That last figure rests on fields in the codex and grok login files
that nothing on main reads today; the plan that places those seats must witness them. The
Gemini seat is sealed on main (`seat_jail.GEMINI_RECORDED_STOP`), not jailed, so it is never
placed in this work and stays on the launching host until agent-harness#1170. The president
and executors are out of scope (ruling B4).

**Cited follow-ons, unchanged:** the cloud adapter (agent-harness#1165) and the self-hosted
HTTPS service ("Plan 3" of the placement plan). Both sit behind this driver.

**No roadmap goal IDs apply.** The v11 roadmap proposal (agent-harness#1394) does not
schedule this work; this plan references agent-harness#896's and agent-harness#1244's
acceptance items and restates none.

## What this plan supersedes and amends

Sections not listed are unchanged. Plan 1a's own Changes, Verification and Acceptance are
history: agent-harness#1246 implemented them. The change that adds this plan also adds a
pointer under each amended plan's title, and changes nothing else in those plans.

**`plans/detailed-remote-sandbox-placement-896-20260929.md`**

| Section | Disposition | Why |
|---|---|---|
| Task: "The cloud path is plan 1a, then 1b, then agent-harness#1165…" | **Superseded.** Order is 1a, this driver, the self-hosted SSH work, then agent-harness#1165. | Maintainer, 2026-10-10 |
| Contract / "Request", "Execution types", "Receipts", "Execution gate" | **Amended** by C1–C13 below | Stated per amendment |
| Contract: every other subsection | Unchanged, still normative | |
| Follow-on / "Plan 1b" | **Superseded in full** by this document. Its rule "backends must tag every remote sandbox with the owner id and lease id at create" is **kept**, as C6. Its "periodic" reaper is **dropped**: see C6. | |
| Follow-on / "Plan 2" (egress allowlist from configuration) | **Unchanged and not scheduled.** The maintainer chose on 2026-10-10 to leave the built-in list as it is. Nothing here changes it or relies on it: a placed seat's namespace is built with an empty private allowlist (C5). | Maintainer, 2026-10-10 |
| Follow-on / "Plan 3" (self-hosted HTTPS) | **Unchanged; sequenced after the SSH work.** | Maintainer, 2026-10-10 |
| Follow-on / "Plans 4a and 4b" | Unchanged; "1b" there now means this plan | |
| RD1 (a), one service and account per user | **Superseded for the SSH work** by "one shared account first" (2026-10-10). Stands for the HTTPS service. | Maintainer, 2026-10-10 |
| RD3: seats only; legs (ii), codex and grok under a subordinate uid on the remote | **Both stand.** Legs (ii) is the last follow-on plan. Until it lands codex and grok are not placed. | |
| RD4 (a), "with a signed attestation" | (a) stands. **The signature is deferred, not dropped,** by the maintainer's ruling of 2026-10-10. It is a named follow-on, required before any gate relies on a far end's claims and before the cloud backend, where the far end is a third party. Until then such claims are unsigned and nothing reads them. | Maintainer, 2026-10-10 |
| RD5, a disk bound per sandbox | **(b):** a measured bound that ends the seat over it, with a stage-size cap and a free-space floor, in the follow-on plans. (a), file-system quotas, is a host option the product does not require. | |
| R7 of the first draft, per-seat memory, CPU and task bounds | **Not in the SSH work, by ruling:** one limit bounds the whole account. See "Consequences". A named follow-on. | Maintainer, 2026-10-10 |
| RD6 | (a) stands for the legacy `host:path` form. (b) is exercised: an optional `ssh` backend, in its follow-on plan. | Maintainer, 2026-10-10 |
| RD2, CD1–CD4 | Unchanged. RD2 describes the HTTPS service; the SSH backend's plan states what SSH does instead. | |

**`plans/detailed-e2b-cloud-backend-896-20260929.md`**

| Section | Disposition |
|---|---|
| Task / "Chain" | **Amended:** 1a → this driver → 4a1 → 4a2 → 4b, sequenced after the SSH work |
| "Placement ordering", item 1, the deadline rule | **Amended** by C2 |
| "Asks of plan 1b": B2 (required capabilities) | **Delivered here** (C5) |
| "Asks of plan 1b": B4 (a control-plane qualification request) | **Delivered here** as the `qualification` workload (C10) |
| "Asks of plan 1b": B1, B3 | **Still owed.** They return to 4a1 as its own first changes. |
| "Asks of plan 2": A1 | **Met another way for placed seats:** C5 gives every placed seat an empty private allowlist. Plan 2 itself stays unscheduled. |
| "Follow-on: plan 4b", the in-VM layout | **Superseded; to be re-derived** from the placed-seat plans when 4b is written |

**`plans/detailed-1244-seat-route-resolver-20261004.md`** (owned by the agent-harness#1244
lane; amended here because the 2026-10-10 rulings change it)

| Section | Disposition |
|---|---|
| "The chain", order of steps 1 and 2 | **Amended for a host with a remote root configured:** the remote rungs of C7 are tried first, in the configured order. The local sandbox is reached only when the walk ends on the launching host. |
| "The chain", step 3 (host-native fill) after a remote refusal | **Amended.** A seat whose walk ends on the launching host continues down this chain from the local sandbox as before. A seat under the capacity bar does not end on the launching host: unless a later remote rung takes it, it is not run, and it is not filled natively there, which is as local as the local sandbox. |
| PR-A3: the `admit()` walk and typed remote codes | **Delivered here** (C3, C7), under the code names this plan gives. PR-A3 then moves the walk into the resolver, unchanged in substance. |

## Research summary

- **The gate.** `_NONLOCAL_EXECUTION_DRIVER = False` (`panel_invoker.py:4166`);
  `_placement_gate` (`:11669-11673`). This plan touches neither.
- **Gaps in the seam as built** (`sandbox_placement.py`): deadlines are non-optional floats;
  `ExecutingBackend` has no admission call, no progress signal, and no bound or cancel on
  any call; a backend is never told its root, the owner or a lease; `ExecSpec` carries an
  argv and one secret; a runtime-attested `committed` or `completed` receipt is built
  nowhere, although `applied_rule` requires both. No test names `ExecSpec` or `ExecResult`
  and no backend exists, so amending them breaks no consumer.
- **Placement codes on main.** Two are in `_HARNESS_DETAIL_CODES`
  (`sandbox_placement_required_unavailable`, `sandbox_placement_driver_unavailable`). The
  seam raises four more that are in no closed list and so surface as an unknown failure:
  `sandbox_placement_ref_invalid`, `sandbox_placement_capability_undeclared`,
  `sandbox_placement_plugin_unavailable`, `sandbox_placement_backend_unregistered`. None
  has a `seat_jail.NOTICES` row. A notice row makes a refusal carry a seat notice: giving
  `sandbox_placement_required_unavailable` one means the fail-closed knob's existing
  refusal gains its fix line as soon as this plan lands. That is the one thing an operator
  can see change.
- **Reusable patterns.** A lock per lease with no pid: `seat_uid.lease_seat_id`. A
  non-blocking lock probe: `convergence/broker/admission.py`. An fsynced append with
  directory fsync: `convergence/event_log._append`. Per-user state: `seat_jail.state_home()`.
  `lease_store.py` and `dispatch_lock.py` decide liveness by timestamp or pid and are not
  reused.
- **Inventories that count new code.** `tests/data/seat_launch_references.json` counts file
  and spawn references per module and function across the package;
  `tests/test_agent_cli_scratch_inventory_1147.py` lists every launch with a computed
  program.
- **CLI.** `phase-loop seat-sandbox qualify|reap` exists for the local jail. The new
  command is therefore `phase-loop placement …`, not `sandbox …`.

## Contract amendments (normative for this plan, every follow-on plan, and agent-harness#1165)

This plan lands these in `advisor_board/CONTRACTS.md`, "Sandbox placement seam". Everything
else there stands: `prepare` is runtime code; `commit` follows both revalidations; launch
is final; backend receipts never make `sandbox_root_applied` true.

- **C1 The unit of execution is a workload the runtime owns, not an argv.** `ExecSpec` is
  `(workload, request, deadline_s, must_end_within_s, output_cap_bytes)`. `workload` is
  `leg` or `qualification`. A backend maps it to the runtime's own packaged worker and
  never receives an argv, a path or an environment built on the launching host. `request`
  is bytes and travels **only** on the backend's one-shot channel. A backend never puts it
  in an environment or a log, and never writes its credential part to a file system; the
  rest (a review bundle, instructions) it may materialise only inside the sandbox it
  created for that workload. `ExecResult` is
  `(sandbox_ref, exit_status, result, truncated)`.
- **C2 A leg may have no deadline, and every started workload has an end it cannot move.**
  - `PlacementRequest.deadline_s` and `ExecSpec.deadline_s` are `float | None`. With a
    deadline, a leg whose deadline exceeds `declaration().max_lifetime_s` fails that rung's
    local checks (C7). Without one, the driver renews while, and only while, the owning process
    holds the lease lock; a backend's `max_lifetime_s` is then a liveness bound (ruling R2).
  - `ExecSpec.must_end_within_s` is fixed when `execute` is called and is never extended by
    a renewal, a reconnect or anything else. It is a number of seconds from the start, not
    a clock time, so the two hosts' clocks need not agree. The caller sets it to the
    earliest of the leg's deadline and the expiry of anything placed with the workload;
    `None` only when neither exists. A backend ends the workload when it is reached, in
    every state the workload can be in, without the launching side's cooperation, and
    reports `sandbox_placement_end_reached`. This plan proves the driver's side (it cancels
    at the end whatever the backend does); the backend's side is owed by each backend
    plan, which must pass the conformance suite this plan ships. A later plan that
    refreshes a credential inside a running seat (a named follow-on by ruling) has to amend
    this rule; nothing else may move the end.
- **C3 Reachability is the driver's; admission is the backend's.**
  - `ExecutingBackend.endpoint(root)` returns the host and port the backend would dial for
    that root, as a name or an address literal, **without resolving anything and without
    any network use**; or `None`, which is allowed only for a backend with no network far
    side. The driver records the endpoint it was given beside the configured root.
  - **The driver itself** resolves the name and opens a connection to that endpoint, within
    `sandbox_policy.probe_timeout_s()` or what is left of the budget if that is less, and
    closes it. A failure of the resolution or of
    the connection is "unreachable", and nothing else is: an exception from `endpoint`
    itself is a local failure of that rung (C7), and a backend with no endpoint is never
    "unreachable".
  - `ExecutingBackend.admit(request, bound)` then sends the admission request. It is
    called after both revalidations and before `commit`. `available()` keeps its meaning:
    a local precondition, no network.
  - **A refusal is an answer, and only an answer is a refusal.** A backend raises
    `PlacementUnavailable(code)` from `admit` only to pass on an answer it received from
    its far end, and that answer means the far end holds nothing for the lease. Everything
    else is **no answer**: the bound passing, the time-out code, a code that is neither
    the runtime's nor registered, any other exception. C7 treats no answer as "something
    may be held". A backend that cannot tell which of the two it has must not raise a
    refusal.
- **C4 Every blocking call is bounded and interruptible.** `admit`, `commit`, `execute`,
  `renew`, `cancel`, `kill`, `list_owned` and `release` take an `OperationBound(timeout_s,
  cancelled)`. A backend returns, or raises `sandbox_placement_operation_timeout`, within
  the bound, and checks `cancelled` while it waits. The driver does not depend on that: it
  gives up on a call that outlives its bound and treats it as no answer. Every parameter
  and field this plan adds to an existing signature (`commit`, `release`, `register_backend`,
  `PlacementRequest`) has a default, because the launch site and the flag-off tests still
  call them in today's form. These bounds are separate from a seat's thinking time: `wait(sandbox_ref, wait_s)` returns an `ExecResult`, or an
  `ExecProgress(sandbox_ref, seq)` whose rising `seq` is a liveness claim for the review
  monitor and nothing else.
- **C5 Required capabilities, and no private endpoint for a placed seat.**
  `PlacementRequest.required_capabilities` for a review leg is `inbound_closed`,
  `one_shot_secret_channel` and `private_ranges_unreachable`. `egress_needs` is **empty**
  for every non-local candidate: the launching host's built-in list describes the launching
  host's own namespace and is not a need of the leg. A backend builds a placed seat's
  namespace with an empty private allowlist. In C7's terms: a required capability the
  backend does not declare fails the rung's local checks, and one that is declared but not
  verified after `commit` sends the rung to "releasing".
- **C6 Owner, lease and root travel with the request.** `PlacementRequest` carries `root`
  (the parsed, sanitized location and the configured backend name: the form
  `sandbox_policy.parse_location` already produces, so userinfo, query and fragment never
  reach a backend), `owner_id` and `lease_id`.
  - The lease id is allocated and its journal entry fsynced **before `admit`**, the first
    call with a remote effect. On a ladder each rung that is asked gets its own lease.
  - A backend tags everything it creates or reserves for a request with the owner id and
    the lease id, from the moment the admission request arrives: a reservation counts, not
    only a finished sandbox. `list_owned(owner_id, bound)` returns `(sandbox_ref,
    lease_id)` pairs and includes reservations; `kill(lease_id, bound)` is targeted by
    lease.
  - **`kill` fences the lease.** Once a backend has been told to kill a lease id, including
    one it has not yet heard of because the admission request is still on its way, it
    never completes an admission or a transfer for that lease id, never starts a workload
    for it, and removes whatever a late request creates for it. The driver, for its part,
    never sends `execute` for a lease it has fenced; that half does not depend on any
    backend.
  - **Scope and lifetime of the fence.** A fence is for one owner id and one lease id. A
    backend's `declaration()` states two things. `late_arrival_s`: the longest time after
    the driver gives up on a request that the request can still take effect on the far
    side (zero for a transport that delivers nothing once its connection is closed).
    `fences`: whether its far side keeps a fence, for at least that long and across its
    own restart. A backend that does not control its far side declares `fences` false.
    For such a backend one empty listing is not a confirmation: a release counts as
    confirmed only when a listing taken after `late_arrival_s` has passed since the lease
    was fenced is empty. A release that ends sooner is unconfirmed, the entry is kept, and
    the reaper lists again until then.
  - **An abandoned lease is the reaper's at once.** When the walk leaves a rung without a
    confirmed release (C7), it marks the entry abandoned and gives up that lease's lock, so
    any reaper, this process's own included, may act on it; the entry is cleared only when
    a kill by that lease id is acknowledged and nothing is listed for it.
  - The reaper decides by lease: it kills a listed sandbox only when that lease's lock is
    free. An owner that died between `commit` and recording its `sandbox_ref` is therefore
    still found, and a live leg of the same owner in that window is never killed.
  - The reaper runs at leg start and by command. A periodic reaper is not built: no backend
    planned so far bills by time. The cloud adapter adds one if it needs one.
- **C7 Where a seat may run: one state machine** (maintainer rulings of 2026-10-10 on "busy
  or down" and on a reachable host that refuses). Everything this plan says about the
  ladder is a restatement of the tables below. The tables are complete: every state has
  exactly one row for every event that can occur in it. "Verification" says what was
  checked against them, how far, and what was not.
  - **Rungs.** The configured remote backends, in the order agent-harness#1246's
    configuration already defines. After them one **last rung**, passed to the walk as a
    value: `local` (the launching host; the default of `PHASE_LOOP_SANDBOX_LAST_RUNG`) or
    `none`. The fail-closed knob forces `none`, and unlike the setting it also refuses legs
    that were never candidates, as it does today. A later ruling that wants another kind
    of last rung adds a value to that one setting and a branch where the walk resolves it;
    a second compute host or the cloud backend needs neither, being one more remote rung.
  - **Before the walk.** A leg that is not a placement candidate is not on the ladder. For
    a candidate the caller's **preflight** runs **once**, on facts the launching host
    already has. If it fails or raises, no remote rung is tried: no rung is left, none has
    answered at capacity, and the attempt ends as the last three rows of the third table
    say, with the preflight's code.
  - **Time.** Four bounds, all enforced by the driver.
    - *The budget.* When the preflight passes the walk gets one budget: the admission wait
      (`PHASE_LOOP_SANDBOX_ADMIT_WAIT_S`, default 600) plus the transfer allowance
      (`PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S`, default 300). `budget_spent`: the time
      since the walk began has reached it. It happens once and stays true.
    - *The admission wait.* `wait_spent`: the time spent in "waiting", summed over all
      rungs, has reached the admission wait. It stays true: a seat waits once, however
      many rungs it is offered. After it, a rung that answers at capacity is left at once.
      The back-off between two requests is the driver's and is never longer than what is
      left of the wait.
    - *The answer bound* (`PHASE_LOOP_SANDBOX_ANSWER_TIMEOUT_S`, default 30). The longest
      the walk waits for one answer: an admission answer, the seal step, or a release (the
      kill and the listing together).
    - *The probe time-out* (the existing setting), for the driver's own connection attempt.

    Every call on a rung is bounded by its own bound or by what is left of the budget,
    whichever is less. Two exceptions: `commit` has no bound of its own, only what is left
    of the budget; and a release keeps the answer bound whatever the budget says, so that
    a rung can always be left. The walk therefore ends within the budget plus one answer
    bound. **Whenever the budget and any other bound end at the same moment, in any state,
    the event that happened is `budget_spent`**, and the code recorded is the budget's.
  - **The lifetime arithmetic is the driver's.** `lifetime_sufficient(remaining_s,
    floor_s)`, used once by the preflight, is true when `remaining_s` is at least the
    floor plus the **whole** budget. `lifetime_at_floor(remaining_s, floor_s)` is the
    guard in the sealing step, on fresh numbers. Because `execute` is never called after
    the budget is spent, a credential that passed the first still passes the second on
    whichever rung seals. Nothing re-runs the first after time has passed.
  - **Code the walk did not write.** A failure of each is an event of the table, never an
    exception that leaves the walk half done. `preflight` runs before the walk.
    `open_lease` and `request_for` raising is `prepare_fail`. `seal` gives `seal_ok`,
    `seal_fail`, `seal_raises` or `seal_no_return`: it is handed the same
    `OperationBound` a backend call gets, and the driver gives up on it at the bound in
    the same way (C4), whether or not it honours it. `cancelled` is the `cancel` event: it
    is checked between steps and passed to every bounded call. A backend's methods are
    the rows for `admit`, `commit` and the release. **`execute` is not an event of the
    walk**: the walk ends when it calls `execute`, and whatever `execute` then does, a
    raise included, is a failure after launch (C11): the leg ends
    `sandbox_placement_lost_after_launch` and no other rung is tried.

  **The alphabet: the states of the rung in hand, and the events that can occur in each.**

  | State | The events that can occur there |
  |---|---|
  | start | `local_ok`, `local_fail`, `budget_spent`, `cancel` |
  | connecting | `connect_ok`, `connect_fail`, `prepare_fail`, `budget_spent`, `cancel` |
  | admitting | `admit_ok`, `admit_capacity`, `admit_refused`, `admit_no_answer`, `budget_spent`, `cancel` |
  | waiting | `retry`, `wait_spent`, `budget_spent`, `cancel` |
  | committing | `commit_ok`, `commit_fail`, `commit_no_answer`, `budget_spent`, `cancel` |
  | sealing | `seal_ok`, `seal_fail`, `seal_raises`, `seal_no_return`, `budget_spent`, `cancel` |
  | releasing | `release_confirmed`, `release_unconfirmed`, `budget_spent`, `cancel` |

  **The transitions: one row for each state and event.** "Left" means the rung is
  finished with that class, one record is added to the trail, and the walk goes on as the
  third table says.

  | State | Event | When | Next | What changes |
  |---|---|---|---|---|
  | start | `local_ok` | every local check passes | connecting |  |
  | start | `local_fail` | a local check fails: no backend is registered for the root's scheme or its plugin does not load, `available()` is false or raises, `endpoint` raises, a required capability is not declared, the deadline exceeds the backend's maximum lifetime, or the workload is `leg` while the driver flag is false | left: **failed locally** | Nothing was sent |
  | start | `budget_spent` | the budget ends before the checks finish | left: **out of time** | Nothing was sent |
  | start | `cancel` | the caller cancels | the attempt ends **cancelled** | Nothing was sent |
  | connecting | `connect_ok` | the driver's own connection attempt succeeds (or the backend has no endpoint, C3), `request_for` returns the request and the lease entry is fsynced | admitting | The admission request is sent. From here until an answer arrives, something may be held on the far side |
  | connecting | `connect_fail` | the driver's own resolution or connection fails or reaches the probe time-out | left: **unreachable** | Nothing was sent |
  | connecting | `prepare_fail` | connected, but `open_lease` or `request_for` raises | left: **failed locally** | Nothing was sent; no lease entry remains |
  | connecting | `budget_spent` | the budget ends first. When it ends at the same moment as the probe time-out, the budget wins | left: **out of time** | Nothing was sent. Running out of time is not evidence that the host is unreachable |
  | connecting | `cancel` | the caller cancels | the attempt ends **cancelled** | Nothing was sent; no lease entry remains |
  | admitting | `admit_ok` | `admit` returns | committing | A slot is held on the far side |
  | admitting | `admit_capacity` | `admit` raises `PlacementUnavailable` with the runtime's capacity code | waiting | An answer from the far end (C3): it holds nothing. **The capacity bar is set for the attempt** |
  | admitting | `admit_refused` | `admit` raises `PlacementUnavailable` with any other code that is the runtime's or one the backend registered, except the time-out code | left: **refused** | An answer from the far end (C3): it holds nothing. The lease entry is cleared |
  | admitting | `admit_no_answer` | anything else: the answer bound passes, or `admit` raises the time-out code `sandbox_placement_operation_timeout`, a code that is neither the runtime's nor registered, or any other exception | releasing | No answer: something may be held |
  | admitting | `budget_spent` | the budget ends before the answer bound does, with the request in flight | releasing | No answer: something may be held |
  | admitting | `cancel` | the caller cancels while the request is in flight | releasing | No answer: something may be held. The cancel is pending |
  | waiting | `retry` | a back-off elapses. It can occur only while the wait is not spent | admitting | The admission request is sent again |
  | waiting | `wait_spent` | the seat's admission wait is used up: now, or already by an earlier rung, in which case this happens at once | left: **capacity** | The lease entry is cleared |
  | waiting | `budget_spent` | the budget ends | left: **capacity** | The lease entry is cleared |
  | waiting | `cancel` | the caller cancels | the attempt ends **cancelled** | Nothing is held; the lease entry is cleared |
  | committing | `commit_ok` | `commit` returns, the digest is equal and every required capability is verified | sealing |  |
  | committing | `commit_fail` | `commit` answers and the answer is not acceptable: it raises `PlacementUnavailable` with a code other than the time-out code, the digest differs, the reference or a claim is invalid, or a required capability is not verified | releasing |  |
  | committing | `commit_no_answer` | `commit` raises the time-out code or any other exception. Its bound is what is left of the budget, so reaching it is `budget_spent` | releasing |  |
  | committing | `budget_spent` | the budget ends during the transfer | releasing |  |
  | committing | `cancel` | the caller cancels | releasing | The cancel is pending |
  | sealing | `seal_ok` | the caller's seal step returns the request (its guard passed) and the budget is not spent | **placed** | **`execute` is called.** Final: the attempt is **placed** |
  | sealing | `seal_fail` | the seal step reports that its guard failed | releasing |  |
  | sealing | `seal_raises` | the seal step raises (for example, its credential read fails) | releasing |  |
  | sealing | `seal_no_return` | the seal step does not return within the answer bound | releasing | Whatever it returns later is discarded |
  | sealing | `budget_spent` | the budget ends before the seal step returns. When both happen at the same moment, the budget wins | releasing | `execute` is not called, even if the guard passed |
  | sealing | `cancel` | the caller cancels | releasing | The cancel is pending |
  | releasing | `release_confirmed` | the kill by lease id is acknowledged and `list_owned` shows nothing for it | left: **refused** | The lease entry is cleared |
  | releasing | `release_unconfirmed` | the kill or the listing fails or raises, or the answer bound passes | left: **refused, unconfirmed** | `sandbox_placement_release_unconfirmed` is recorded; **the lease entry is kept for the reaper and the lease stays fenced** (C6) |
  | releasing | `budget_spent` | the budget ends during the release | releasing | The release goes on: its bound is the answer bound, not the budget. The budget is spent for what the walk does next |
  | releasing | `cancel` | the caller cancels | releasing | The release in flight is finished. The cancel is pending |

  Entering "releasing" fences the lease first and then sends the kill by lease id. "The
  cancel is pending" means: the release is finished, and then the attempt ends cancelled,
  whether or not the release was confirmed.

  | After a rung is left, when | The walk |
  |---|---|
  | A cancel is pending | Ends **cancelled** |
  | No cancel is pending; another remote rung exists and the budget is not spent | Starts that rung |
  | No cancel is pending; no further remote rung, or the budget is spent; the last rung is `local`; no rung has answered at capacity | Ends on **the launching host** |
  | No cancel is pending; no further remote rung, or the budget is spent; the last rung is `local`; some rung has answered at capacity | Ends **not run**, `sandbox_placement_capacity_exhausted` |
  | No cancel is pending; no further remote rung, or the budget is spent; the last rung is `none` | Ends **not run**, with the code of the last rung left, or `sandbox_placement_required_unavailable` under the knob |

  **The record each rung leaves in the trail**, so that every code in this plan's list is
  emitted by a transition:

  | Record | Code |
  |---|---|
  | failed locally | `sandbox_placement_driver_unavailable` (flag off); `sandbox_placement_capability_unmet` (a required capability not declared); `sandbox_placement_backend_unregistered`, `sandbox_placement_plugin_unavailable` or `sandbox_placement_refused` for the other local checks and for `prepare_fail`, as the seam raises them today |
  | unreachable | `sandbox_placement_unreachable` |
  | out of time | `sandbox_placement_budget_spent` |
  | capacity | `sandbox_placement_at_capacity` |
  | refused, from `admit_refused` | The code the backend raised: one of the runtime's (`sandbox_placement_not_enrolled`, `sandbox_placement_identity_mismatch`, `sandbox_placement_workload_unsupported`) or one it registered |
  | refused, after a release | The code of the event that sent the rung to "releasing". No answer (`admit_no_answer`, `commit_no_answer`, `seal_no_return`): `sandbox_placement_operation_timeout` for a bound or the time-out code, `sandbox_placement_code_invalid` for a code that is neither the runtime's nor registered, `sandbox_placement_refused` for any other exception. `budget_spent`: `sandbox_placement_budget_spent`. `commit_fail`: the code `commit` raised; `sandbox_placement_capability_unmet`; `sandbox_placement_ref_invalid` or `sandbox_placement_capability_undeclared`, as the seam raises them today; `sandbox_placement_refused` for a digest that differs. `seal_fail`, `seal_raises`: `sandbox_placement_refused` |
  | refused, unconfirmed | The same code, and `sandbox_placement_release_unconfirmed` beside it |
  | cancelled | No code: the state the rung was in at the cancel, and how its release ended (none needed, confirmed, unconfirmed) |
  | placed | No code |

  What follows from the tables, stated once each because a ruling or a reviewer asked:
  - **A seat is never run twice and never moves after `execute`.** `execute` is reached
    from one row, only for a lease that was never fenced, and ends the walk.
  - **A full host never sends load to the launching host.** The capacity bar is set by the
    first capacity answer on any rung and no row clears it. Under it a later remote rung
    may still take the seat (question Q4).
  - **A seat waits once.** The wait is one sum over all rungs; no row sends a second
    request to a rung after it is spent.
  - **Before `execute`, a rung that cannot be released with confirmation does not end the
    attempt** (question Q5). Nothing ran there and no credential was sent, so going on
    cannot run the seat twice; the fence and the kept lease entry are what deal with
    whatever was left.
  - **Whatever may be held always has a lease entry.** The entry is on disk before the
    first request is sent. It is cleared only by an answer that means nothing is held
    (a refusal, a capacity answer on leaving, a confirmed release), and kept otherwise.
  - **A cancel never moves the walk on and never drops a rung from the trail.** In
    "start", "connecting" and "waiting" nothing is held and the attempt ends at once. In
    every other state the lease is fenced and released first. The outcome is
    **cancelled**; `place` raises what main raises for a cancelled review operation, with
    the trail attached.
  - **Capacity is the runtime's word.** There is one capacity code and it is the runtime's
    (`sandbox_placement_at_capacity`). A backend answers capacity only by raising it; any
    other code is a refusal or no answer. Which of its own conditions a backend reports as
    capacity is fixed in that backend's plan; the driver cannot check that choice.
  - **Every exit carries the trail:** for each rung the walk was on, in order, its name
    and its record. It is returned with "placed", with "the launching host" and with "not
    run", and attached to what a cancel raises. A decision that ends on the launching host
    also carries the mark that the local route must be a tooled one (a seat that was a
    candidate never runs sealed); the plan that wires the launch site honours it. That
    plan is also held to this: the leg's machine-readable record carries the trail as a
    list, not folded into the one string `sandbox_root_reason` holds today (`<name>:
    <root>: <code>` for a named root); a trail exists on a placed and on a not-run leg,
    where today sandbox facts are recorded only for a leg that runs locally; and the
    notice `seat_sandbox_root_fell_back`, whose text today says the configured root was
    unreachable, gets text that is true after a refusal as well.
  - **Where the decision sits.** Where `commit` is called today, after local staging and
    both revalidations.
  - **Monitoring while it walks.** The monitor record carries `placement_wait` while a rung
    is in "waiting", and the notice `seat_placement_waiting` is shown. A leg's stall clock
    starts when `execute` returns. For a bounded leg the whole walk is charged to its
    deadline, as the login wait is.
- **C8 The seal step is the walk's, so nothing sits between "placed" and `execute`.** The
  caller gives `place` a seal step: it applies the caller's guard on fresh numbers and
  returns the request. `place` calls it in the sealing state and then calls `execute`
  itself. There is therefore no moment at which a caller holds an admitted slot and has
  not launched.
- **C9 Runtime receipts.** The driver, which lives in `sandbox_placement` beside the seal,
  builds `committed` when `commit` returned for the digest the runtime computed, `launched`
  when it called `execute`, and `completed` when it received a terminal `ExecResult` for
  the same `sandbox_ref` whose result echoes the digest of the request the runtime sent.
  `sandbox_root_applied=true` for a placed leg therefore means: the runtime sent this leg to
  that backend and received its result on the same sandbox. It does not mean the runtime
  observed the seat's confinement; that is `sandbox_placement_verified`, and every entry
  there is a backend claim unless the runtime itself measured it.
- **C10 The gate governs legs; qualification is exempt.** `PlacementRequest.workload` is
  visible to the driver and to `admit`. Only a qualification entry point builds a
  `qualification` request: it transfers a synthetic tree, its records never count as an
  applied placement, and it may be driven while `_NONLOCAL_EXECUTION_DRIVER` is false. **The
  driver itself refuses a `leg` request while the flag is false**: it is one of the local
  checks behind C7's `local_fail`, in `place`, not left to its callers. A backend that cannot run a
  workload refuses it in `admit` (`sandbox_placement_workload_unsupported`), so nothing is
  transferred for a workload that will not run. The flag turns on in the plan after which
  a real backend runs a seat end to end, not before.
- **C11 After `execute`: confirmed release, and a finished review is kept.** `release` on a
  launched placement returns only when the sandbox is confirmed gone (`kill` by lease id,
  then absent from `list_owned`). If the result was already received and ingested, an
  unconfirmed kill does **not** discard it: the leg keeps its result, carries the notice
  `sandbox_placement_release_unconfirmed`, and the lease entry stays for the reaper.
  Without a result, an unconfirmed kill ends the leg with
  `sandbox_placement_lost_after_launch`. Nothing after `execute` ever starts the seat
  again or tries another rung.
- **C12 A lost connection after launch** (ruling Q1 of 2026-10-10: the far end keeps a
  started seat alive for a limited time and the launching host resumes it, tied to that
  run). **This plan does not build it.** As built here, a backend whose connection is lost
  after `execute` raises, and the leg ends with `sandbox_placement_lost_after_launch`. The
  reconnect follow-on plan amends exactly two things built here: what `wait` may return,
  and the loop in `run_placed`. Until then `wait` returns only a result or progress, and
  the "connection lost" case in this plan's tests describes the runtime **before** that
  plan; it is replaced there and is not a permanent rule. The follow-on is held to these
  invariants, stated now so that nothing else built here has to be undone:
  - the end of C2 is fixed at launch and no reconnect extends it; it applies while
    attached and while detached;
  - there is one enforcement point on the far side for a kept workload's end; the
    workload cannot influence it; and its failure to act is bounded by something
    independent of it;
  - an explicit end or cancel from the driver is always honoured at once. Silence is
    treated as a lost connection. An owner that was killed says nothing, so it looks like
    a lost connection too; it is ended by the reaper (C6) or by C2's end, whichever comes
    first;
  - resume is bound to the lease id of C6 and to the principal that launched it; a detached
    leg is never started again and never moves;
  - a finished result survives a detach.
- **C13 A backend accounts for what it leaves behind.** A backend's plan states, for each
  process it runs on the far side, by name, what dies with it; and for a clean exit, a
  kill of each named process, an out-of-memory kill and a reboot, what state remains
  (processes, files, credentials in memory) and what removes it. "Nothing at rest" may be
  claimed only where it holds by construction; elsewhere the limit is stated. The tests
  name the process they kill. This is a rule about what later plans must write; it has no
  test in this plan.

## Consequences the maintainer should see

These follow from the rulings as recorded. The first group is read off the tables: each
cites the named orderings (N1 to N20, under "Verification") whose outcome it states, and
says nothing those orderings do not produce. The second group comes from the rest of the
contract.

**From the tables.**

- **A compute host that is down, misconfigured or refusing sends its seats to the
  launching host**, when no other remote rung takes them, no rung has answered "full" and
  the last rung is `local` (N1, N18; with the last rung `none` the seat is not run: N19).
  Unreachable, another build installed there, a revoked key, a failed host check: each is
  a typed notice with its fix line, and then the seat runs on the launching host. That is
  the ruling ("for now the local fallback is fine"). A compute host that is quietly broken
  for everyone therefore puts the whole load back where it started, with notices on every
  board and nothing else to stop it.
- **A host that accepts the connection and then stops answering costs each seat two
  answer bounds, and can be left holding something** (N2). The admission gets no answer
  within the answer bound; the kill gets none either; the rung is recorded "refused,
  unconfirmed", its lease is fenced and its entry kept. The seat then goes on. **It can
  run on the launching host while a slot and a copy of the staged tree stay reserved on
  the compute host, until a later reaper's kill is confirmed.** No credential and no
  workload were sent there. Whether the seat should go on at all is question Q5. If the
  kill is confirmed, nothing is left (N3).
- **The capacity rule is the only thing that holds load off the launching host, and it
  works only when the compute host manages to say "full".** A host that is overloaded but
  answers with any other code, or does not answer, sends its load to the launching host
  (N1, N2, N3). Which conditions a backend reports as capacity (its seat cap; its disk
  floor) is decided in that backend's plan, and the driver cannot check it.
- **One "full" answer bars the launching host for the rest of the attempt, whatever
  happens afterwards.** If the same rung then admits the seat and the transfer fails for
  an unrelated reason, the seat is not run unless a later remote rung takes it (N4 against
  N5). A later rung that is unreachable does not lift the bar (N9).
- **A full compute host costs a board its placed seats, unless another remote rung takes
  them.** A seat waits once, for the admission wait, over all rungs together, and is then
  not run (N6, N7). A second remote rung that admits it places it, whether or not the
  wait is already spent (N5, N8). A board that needs those seats to reach its quorum, and has no
  such rung, does not reach it.
- **A slow rung can starve a healthy one, and running out of time is not being full.**
  The walk has one budget. If a remote rung uses it up, in a transfer, in the seal step
  or in a release, no further remote rung is started (N10, N20), and the seat goes to the
  launching host (N10, N11, N20) unless some rung has answered "full", when it is not run.
  A compute host that is too slow to take the staged tree within the transfer allowance
  therefore sends its seats back, as a broken one does.
- **A seat whose credential cannot be read at the last moment is released from that
  rung, and the walk goes on.** With no other remote rung it ends on the launching host
  (N12), where the local route's own rules then decide.
- **A cancel can leave something behind too** (N14): a cancel while a request is in
  flight, with a kill that is not confirmed, ends the attempt with a fenced lease and a
  kept entry for the reaper. A cancel while waiting leaves nothing (N13).

**From the rest of the contract.**

- **The real floor for placement is 45 minutes of token life by default, not 30.** A seat
  is placed only if its credential outlasts the ruled floor (30 minutes) plus the budget
  (ten minutes of waiting and five of transfer by default). A token with between 30 and 45
  minutes left runs on the launching host. Raising the wait raises this number.
- **A placed seat is ended when its credential expires, even while it is working.** C2's
  end is the earliest of the leg's deadline and that expiry. Under heartbeat-only, where a
  local seat has no deadline and silence never ends it, a placed seat therefore has a hard
  limit equal to its token's remaining life, which can be as little as the floor; it is
  then lost and is not run again. This takes effect only when the flag turns on; the plan
  that does that must amend the monitoring policy section of the contract and say this
  again.
- **Reaching the launching host does not always mean the review happens.** The local
  route's own rules apply there, re-read at launch, after a walk that may have taken the
  whole budget and one answer bound more: a login that would have been long enough at the
  start may no longer be. A seat whose local route is the sealed one is not run.
- **A backend that cannot fence, and whose late-arrival time is longer than the answer
  bound, shows every release before `execute` as unconfirmed** (C6): the release ends
  before a listing can count. The entry is cleared by a later reaper. The cloud backend
  is expected to be one.
- **Boards run from a source checkout** (the usual way boards run in this repository) are
  never the build a compute host has installed. The SSH follow-on plan should make that a
  preflight failure, so those boards go straight to the last rung without a round trip.
- **One limit for the whole account** on the compute host. One seat's memory use can get
  another user's seat killed, and that seat is not run again.
## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `PlacementRequest` — modify — optional deadline; `workload`, `required_capabilities`,
  `root`, `owner_id`, `lease_id`; `egress_needs` empty for a non-local candidate (C2, C5,
  C6, C10).
- `ExecSpec`, `ExecResult` — modify; `ExecProgress`, `OperationBound` — add (C1, C2, C4).
- `ExecutingBackend` — modify — `endpoint`, `admit`; the bound on each blocking call;
  `list_owned` and `kill` by lease; `fences` and `late_arrival_s` in the declaration (C3,
  C4, C6).
- `PLACEMENT_CODES` and `register_backend(scheme, backend, codes)` — add / modify — the
  runtime's closed code list, including the one capacity code, and registration of a
  backend's own codes, which only supply fix lines (C7). The four codes the seam already
  raises are entered here.
- `LADDER_TABLE` — add — C7's alphabet and its transition and after-a-rung tables as
  data. `place` is written against it. The model-based test compares it with its own
  literal copy of C7, so a change to it is a visible change to a test fixture.
- `PlacementDecision` and `place(rungs, last_rung, prepared, request_for, open_lease, *,
  preflight, seal, driver_enabled, cancelled, clock)` — add — the walk of C7, with C3's
  connection attempt and C8's seal step. The flag is passed in, so `sandbox_placement`
  does not import the launch module. The clock is passed in, with the monotonic clock as
  its default, so a test can make time an event. It ends in one of: placed (`execute` has been
  called; a `LegPlacement`), the launching host (with the "never sealed" mark), or not
  run (with its code), each with the trail; or it raises the cancel, with the trail
  attached. It owns the budget.
- `lifetime_sufficient`, `lifetime_at_floor` — add — the two comparisons of C7, pure
  functions of two numbers and the two settings.
- `run_placed(placement, *, on_progress, cancelled) -> ExecResult` — add — everything after
  `execute`: the `wait` loop, renewal, cancel, C2's end and C11.
- `LegPlacement.record_runtime(step)` — add — the only builder of runtime `committed`,
  `launched` and `completed` receipts for a non-local placement (C9).

### `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` (create)
- `owner_id()` — add — a per-user random id under `state_home()/phase-loop/` (0600).
- `open_lease(backend_name, root) -> Lease` — add — allocates the lease id and writes one
  file under `state_home()/phase-loop/placement-leases/` (directory 0700, file 0600),
  fsynced with its directory before `admit`, held under `flock` by the owning process until
  the rung is left or the leg ends. An abandoned lease gives the lock up at once and keeps
  its entry, marked abandoned (C6). It records the lease id, the backend name, the
  sanitized root, the `sandbox_ref` once known, `created_at`, `fenced_at` and
  `confirmed_killed_at`. It never records request or result bytes.
- `Lease.heartbeat(...)` — add — renews on an interval and stops with the leg (C2).
- `reap(backends, bound)` — add — driven by the journal: a backend is contacted only when
  an entry naming it exists with a free lock; with none, no call is made and no plugin is
  imported. For a contacted backend it applies C6's rule, confirms, then clears the entry.
  An entry whose lease the backend no longer lists **and whose kill it has acknowledged**
  is cleared; an abandoned entry is never cleared on an empty listing alone, and for a
  backend that does not fence, never before `late_arrival_s` has passed since `fenced_at`
  (C6). Liveness is never decided by pid or age.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `candidate_roots(...)` — add — the remote rungs: every configured non-local root that
  is written as a URL, in the configured order. The legacy `host:path` form is never a
  rung: it stays record-only, as RD6 (a) rules. A root whose scheme has no registered
  backend, or whose plugin does not load, is still a rung; it fails its local checks
  (C7). No backend method is called and nothing is probed.
- `last_rung()` — add — reads `PHASE_LOOP_SANDBOX_LAST_RUNG`: `local` (default) or `none`;
  any other value is `sandbox_config_invalid`. The fail-closed knob forces `none`.
- `admit_wait_s()`, `transfer_allowance_s()`, `answer_timeout_s()` — add — the three
  settings of C7, read with the `_env_int` idiom; defaults 600, 300 and 30.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `seat_jail.py` (modify)
- `_HARNESS_DETAIL_CODES` and `NOTICES` — modify — every placement code in the list below
  becomes a member with a `(what, why, fix)` row. Nothing else in `panel_invoker.py`
  changes: the launch site and the flag are untouched.

  The codes: the two already listed; the four the seam already raises; and
  `sandbox_placement_lost_after_launch`, `sandbox_placement_end_reached`, `sandbox_placement_capability_unmet`,
  `sandbox_placement_capacity_exhausted`, `sandbox_placement_unreachable`,
  `sandbox_placement_not_enrolled`, `sandbox_placement_identity_mismatch`,
  `sandbox_placement_refused`, `sandbox_placement_workload_unsupported`,
  `sandbox_placement_operation_timeout`, `sandbox_placement_code_invalid`,
  `sandbox_placement_release_unconfirmed`, `sandbox_placement_at_capacity`,
  `sandbox_placement_budget_spent`,
  `seat_placement_waiting`.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … A detail is one of: a HARNESS CODE — a
  fixed string this runtime itself emits (`_HARNESS_DETAIL_CODES`)". Members are added by
  that mechanism; no template or category is added.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `placement` command, action `reap` — add — runs `placement_lease.reap` for the configured
  backends. Its `dest`s are uniquely named.

### `phase-loop-runtime/src/phase_loop_runtime/placement_conformance.py` (create)
- A conformance suite, parametrised over a backend factory — add — in the package, not
  under `tests/`, so a backend delivered outside this repository can run it. It checks the
  obligations this contract puts on a **backend**, which the driver's own tests can only
  see from the driver's side: the workload is ended at `must_end_within_s` with no further
  call from the driver (C2); every blocking call honours its bound and its cancel (C4);
  everything is tagged, listed and killed by lease id, reservations included (C6); **a
  kill fences the lease: an admission that completes after the kill leaves nothing
  listed, and `execute` for that lease is refused** (C6); a refusal from `admit` leaves
  nothing behind. For the fence the factory must offer one thing: a way to make an
  admission complete after a kill. A backend that cannot offer it declares that it cannot
  fence and is held to the listing rule of C6 instead. That a far side keeps a fence
  across its own restart cannot be tested here; it is reviewed in each backend's plan. It
  cannot observe what a backend on another machine puts in an
  environment or a log (C1); that stays a matter for each backend's own plan and review.
  This plan runs it against its fakes, including fakes built to violate each obligation,
  which it must reject. Every backend plan runs it against its backend.

### `phase-loop-runtime/tests/test_placement_ladder_model.py`, `tests/test_placement_driver.py`, `tests/test_placement_lease.py` (create); `tests/test_sandbox_placement.py`, `tests/test_seat_notices.py`, `tests/data/seat_launch_references.json`, `tests/test_agent_cli_scratch_inventory_1147.py` (modify)
- The falsifiers under "Verification".
- The inventories gain the rows the new modules and the `cli.py` edit add; the PR body lists
  them.
- `tests/test_sandbox_placement.py` keeps every flag-off test unchanged: the flag does not
  move. Its fake backend gains the new protocol members.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify —
  amendments C1–C13 in "Sandbox placement seam", the C7 ladder's tables verbatim; the placement codes
  under "Leg `detail` vocabulary". The execution-gate and fail-closed paragraphs are **not**
  changed here: they describe the flag-off runtime, which is still what ships.
- `docs/phase-loop/convergence-runtime.md` — modify — the lease directory,
  `phase-loop placement reap`, and the settings this plan adds (the last rung, the
  admission wait, the transfer allowance, the answer bound); they have no effect until a backend exists and
  the flag is on, and the text says so.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`, which notes that the
  fail-closed knob's refusal now carries a fix line.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md`, `docs/advisor-board-capabilities-card.md`
  — none.

## Dependencies & order
1. Needs plan 1a (merged) only. Independent of the launch-factoring plan.
2. It touches `panel_invoker.py` and `seat_jail.py` for vocabulary and notice rows only.
3. No agy route-core file is edited. The next release cut requalifies agy as usual.
4. Order: the tests first, failing on the missing symbols (the RED receipt); the seam types;
   `placement_lease`; `place` and `run_placed`; `sandbox_policy`; the codes; the CLI.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_placement_ladder_model.py tests/test_placement_driver.py \
  tests/test_placement_lease.py tests/test_sandbox_placement.py \
  tests/test_sandbox_policy.py tests/test_seat_notices.py tests/test_seat_owner_notices.py \
  tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py \
  tests/test_panel_leg_status_detail_1096.py tests/test_launchspec_golden.py
ruff check .
```

Run on Python 3.12 and 3.10. The backends are conformant in-process fakes that count every
call and record the order; their endpoints are real loopback sockets the test opens or
leaves closed, so the driver's own connection attempt is exercised, not stubbed. `place`
and `run_placed` are driven directly; `_default_spawn` is not involved. Each case is
control-green and red under its mutation.

**The ladder is tested from its tables, and what that covers is stated exactly.**

*What is enumerated.* One attempt for one seat: one walk over one, two or three remote
rungs, with either last rung, after a preflight that passed. The alphabet is C7's first
table. Time is events, not numbers: `budget_spent` and `wait_spent` each become true and
stay true. A backend is the events it produces. What may be held on a far side is tracked
from those events alone (a request that was sent and not answered may have created
something), independently of what the walk does about it.

*How far.* Not "every ordering up to a length": the retry loop makes orderings unbounded.
The test builds the **state graph**: every state the walk can reach (the rung in hand,
its state, the walk's flags, the trail and what each rung may hold; never a count), and
every transition out of each, until no new state appears. A property that holds in every
reachable state and on every transition holds on every ordering of any length. Wherever
this plan says the ladder is checked, it means this graph and nothing wider.

*What that does not cover, and what does.*

| Not in the model | Covered by |
|---|---|
| Numbers: that the budget, the wait and the lifetime arithmetic add up | "Lifetime arithmetic with numbers" and the boundary case, in the last table |
| The launching process killed or restarted during a walk | I1 and I2 fix what is on disk at every moment; what a reaper then does with it is the SIGKILL case and the kept-entry case, in the last table |
| Two attempts at once; two processes on one lease directory | "Two walks at once", in the last table. Nothing else in this plan claims it |
| Anything after `execute` | The `run_placed` cases, in the last table |
| What a backend does on its far side, the fence included | The conformance suite; a fence kept across a far-side restart, by review of each backend's plan |
| Whether the tables are the right reading of the rulings | The maintainer: Q4 and Q5 |

`tests/test_placement_ladder_model.py`:
1. **Totality.** For the alphabet, `LADDER_TABLE` has exactly one row for every state and
   event, and no row for any other pair.
2. **The fixture.** The test holds its own literal copy of C7's tables and asserts
   `LADDER_TABLE` equals it.
3. **The reference.** An interpreter of the tables, written in the test, reading the
   test's own copy of them and importing nothing from the product, builds the state graph
   for each of the six configurations.
4. **The real walk.** For every transition in the graph the test drives the real `place`
   through one complete ordering that contains it: the shortest way to the transition's
   state, the transition, the shortest way to an outcome. The fake backends, the loopback
   endpoints, an injected clock and an injected lease opener are scripted so that exactly
   those events happen. No real time passes and no file is synced to disk. It asserts that
   every transition was driven, not a count.
5. **The comparison.** What `place` did against what the reference says: the outcome, the
   trail's records, the sequence of backend calls, the lease journal's entries at the end,
   and whether the entry was present at each backend call.
6. **The properties**, on every state of the reference and on what each real run recorded:

| Id | Property |
|---|---|
| P1 | `execute` is called at most once, and exactly once when the outcome is "placed" |
| P2 | The outcome is never the launching host once any rung has answered at capacity, whatever later rungs did |
| P3 | The outcome is "not run" only when some rung answered at capacity or the last rung is `none` |
| P4 | Nothing happens on any rung after `execute` |
| P5 | After a cancel nothing happens except finishing a release, and the outcome is "cancelled" |
| P6 | Whatever may be held on a rung that did not execute has a lease entry and a fenced lease |
| P7 | On every exit the trail names every rung the walk was on, once, in order; a cancelled attempt's last record is the rung in hand, with the state it was in at the cancel and how its release ended |
| P8 | No rung is started, and `execute` is never called, after the budget is spent |
| P9 | One wait per seat: no back-off and second request after the wait is spent, on any rung |
| P10 | No lease entry is kept for a rung on which nothing can be held |
| P11 | A kill by lease id was sent for every rung on which something may be held and which did not execute |
| P12 | `execute` is never sent for a fenced lease |
| P13 | The record tells the truth about the rung: "unreachable" exactly when the driver's own connection attempt failed; "capacity" exactly when the rung's last answer was a capacity answer; "failed locally", "unreachable" and "out of time" only when no request was ever sent to it; "refused, unconfirmed" exactly when something may still be held there |
| P14 | `execute` is called only for a rung whose seal step returned the request in time, its guard having passed |
| I1 | At every moment, whatever may be held on a far side already has a lease entry on disk |
| I2 | At every moment a request is in flight, its lease entry is on disk |
| L1 | No dead end: from every reachable state an outcome can be reached, and a rung in "releasing" can always be left |

The planning lane ran a model of the same tables before this text was written: no
reachable state violates a property, and every mutation below turned at least one red.
Its numbers are in the pull request, not here; the test asserts coverage, not a number.

**Mutations, each of which must turn the model-based test red.** The first group is made
to the product's walk. The second is made to `LADDER_TABLE`; the fixture comparison
catches each of those first, and the second column says what catches it when the fixture
is changed with it. The column is what the planning model reported for the same mutation.

| Mutation | Red |
|---|---|
| A non-capacity refusal ends the attempt instead of leaving the rung | P3 |
| The capacity bar is not set by a capacity answer | P2 |
| The capacity bar is cleared by a later admission | P2 |
| A cancel moves on to the next rung | P5, P6, P11, P13 |
| An unconfirmed release clears the lease entry | I1, P6 |
| An unconfirmed release before `execute` ends the attempt | P3 |
| The walk continues after `execute` | P1, P4 |
| An unreachable rung is left without a trail record | P7 |
| A cancel in start, connecting or waiting ends the attempt without a record for the rung in hand | P7 |
| A cancel that needs a release records the release's class, not the state at the cancel | P7 |
| A rung backs off and asks again after the seat's wait is spent | P9 |
| A rung is fenced and left without a kill being sent | P11, P13 |
| `execute` is sent for a fenced lease | P12 |
| A cancel while waiting keeps the lease entry | P10 |
| Leaving a rung for capacity keeps its lease entry | P10 |
| A rung is started after the budget is spent | P8 |
| In the table: an admission that got no answer is treated as an answered refusal: no release | P6, P11, P13 |
| In the table: the budget ending during an admission leaves the rung without a release | P6, P11, P13 |
| In the table: the budget ending in the seal step still launches | P8, P14 |
| In the table: a seal step that overran its bound still launches | P14 |
| In the table: a failed transfer leaves the rung without a release | P6, P11, P13 |
| In the table: a failed guard still launches | P14 |
| In the table: a failed guard leaves the rung without a release | P6, P11, P13 |
| In the table: a cancel during the transfer ends the attempt without a release | P6, P7, P11 |
| In the table: running out of time while connecting is recorded as unreachable | P13 |
| In the table: a rung left at capacity is recorded as refused | P13 |
| In the table: a lease that could not be written is recorded as unreachable | P13 |
| In the table: the budget ending during a release abandons the release as if it were confirmed | P13 |
| In the table: a row is deleted | the totality check |
| In the table: a row is added for an event the state cannot have | the totality check |

**Named orderings.** Each is one path through the graph, kept as a test of its own so
that a failure reads as the finding or the consequence it answers. Events are C7's;
"/" separates rungs. The last rung is `local` unless the row says otherwise. Outcome,
trail and what is left behind are what the tables give.

| Id | Ordering | Events, rung by rung | Outcome | Trail | Left behind |
|---|---|---|---|---|---|
| N1 | Two remote rungs both refuse for a reason other than capacity | `local_ok` `connect_ok` `admit_refused` / `local_ok` `connect_ok` `admit_refused` | **The launching host** | 1: refused; 2: refused | nothing |
| N2 | A host that accepts the connection and then stops answering: `admit` gets no answer and the kill is not confirmed either | `local_ok` `connect_ok` `admit_no_answer` `release_unconfirmed` | **The launching host** | 1: refused, unconfirmed | rung 1: something may be held; lease entry kept, fenced |
| N3 | `admit` gets no answer; the kill by lease id is confirmed | `local_ok` `connect_ok` `admit_no_answer` `release_confirmed` | **The launching host** | 1: refused | nothing |
| N4 | At capacity, then admitted on the same rung, then the transfer fails; no other remote rung | `local_ok` `connect_ok` `admit_capacity` `retry` `admit_ok` `commit_fail` `release_confirmed` | **Not run**, `sandbox_placement_capacity_exhausted` | 1: refused | nothing |
| N5 | The same on rung one, and rung two then takes the seat | `local_ok` `connect_ok` `admit_capacity` `retry` `admit_ok` `commit_fail` `release_confirmed` / `local_ok` `connect_ok` `admit_ok` `commit_ok` `seal_ok` | **Placed** on rung 2 | 1: refused; 2: placed | nothing |
| N6 | A full host: at capacity until the wait is spent; no other remote rung | `local_ok` `connect_ok` `admit_capacity` `retry` `admit_capacity` `wait_spent` | **Not run**, `sandbox_placement_capacity_exhausted` | 1: capacity | nothing |
| N7 | The wait is spent on rung one; rung two also answers at capacity | `local_ok` `connect_ok` `admit_capacity` `wait_spent` / `local_ok` `connect_ok` `admit_capacity` `wait_spent` | **Not run**, `sandbox_placement_capacity_exhausted` | 1: capacity; 2: capacity | nothing |
| N8 | The wait is spent on rung one; rung two admits | `local_ok` `connect_ok` `admit_capacity` `wait_spent` / `local_ok` `connect_ok` `admit_ok` `commit_ok` `seal_ok` | **Placed** on rung 2 | 1: capacity; 2: placed | nothing |
| N9 | Rung one answers at capacity until the wait is spent; rung two is unreachable | `local_ok` `connect_ok` `admit_capacity` `wait_spent` / `local_ok` `connect_fail` | **Not run**, `sandbox_placement_capacity_exhausted` | 1: capacity; 2: unreachable | nothing |
| N10 | The budget is spent while rung one is committing; a second remote rung is configured | `local_ok` `connect_ok` `admit_ok` `budget_spent` `release_confirmed` | **The launching host** | 1: refused | rung 2 never started |
| N11 | The budget is spent in the seal step, and the guard would have passed | `local_ok` `connect_ok` `admit_ok` `commit_ok` `budget_spent` `release_confirmed` | **The launching host** | 1: refused | nothing |
| N12 | The seal step's credential read raises | `local_ok` `connect_ok` `admit_ok` `commit_ok` `seal_raises` `release_confirmed` | **The launching host** | 1: refused | nothing |
| N13 | Cancel while waiting at capacity | `local_ok` `connect_ok` `admit_capacity` `cancel` | **Cancelled** | 1: cancelled in "waiting" | nothing |
| N14 | Cancel while an admission is in flight; the kill is not confirmed | `local_ok` `connect_ok` `cancel` `release_unconfirmed` | **Cancelled** | 1: cancelled in "admitting", release unconfirmed | rung 1: something may be held; lease entry kept, fenced |
| N15 | Cancel while committing; the kill is confirmed | `local_ok` `connect_ok` `admit_ok` `cancel` `release_confirmed` | **Cancelled** | 1: cancelled in "committing", release confirmed | rung 2 never started |
| N16 | Cancel while a release is in flight after a failed transfer | `local_ok` `connect_ok` `admit_ok` `commit_fail` `cancel` `release_confirmed` | **Cancelled** | 1: cancelled in "releasing", release confirmed | rung 2 never started |
| N17 | The first rung is unreachable and the second places the seat | `local_ok` `connect_fail` / `local_ok` `connect_ok` `admit_ok` `commit_ok` `seal_ok` | **Placed** on rung 2 | 1: unreachable; 2: placed | nothing |
| N18 | A `leg` workload with the driver flag false, two remote rungs | `local_fail` / `local_fail` | **The launching host** | 1: failed locally; 2: failed locally | nothing |
| N19 | One unreachable rung; the last rung is `none` | `local_ok` `connect_fail` | **Not run**, with the code of the last rung left (unreachable) | 1: unreachable | nothing |
| N20 | The release of rung one outlasts the budget; a second remote rung is configured | `local_ok` `connect_ok` `admit_no_answer` `budget_spent` `release_confirmed` | **The launching host** | 1: refused | rung 2 never started |
**The rest of the contract.**

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| `admit` raises: the runtime's capacity code; a code the backend registered; an unregistered code, prose, a path, 200 characters; an exception of another type | Waiting; a refused rung with no kill sent; no answer: the lease is fenced, a kill by lease id is sent, and the record is `sandbox_placement_code_invalid` (`sandbox_placement_refused` for the other exception), the text appearing in no record or log | Treat a registered code as capacity; record `str(exc.reason)`; treat an unregistered code as an answer |
| With the defaults and numbers: the credential has exactly 2700 seconds left (floor plus the whole budget); rung one is at capacity until the wait is spent, 600 seconds later; rung two admits and commits; the seal step sees 2100 seconds, above the 1800-second floor | Placed on rung two. One second less at the start: the launching host, nothing sent | Evaluate the preflight's sum again before a later rung |
| The preflight fails, or raises | The last rung is resolved at once with the preflight's code; zero connection attempts | Start the walk anyway |
| Any ordering that ends on the launching host for a candidate seat | The decision carries the "never sealed" mark | Drop the mark |
| `execute` raises at once | `sandbox_placement_lost_after_launch`; the lease is released under C11; no call on any other rung | Return the seat to the ladder |
| Two walks at once for one owner on one backend, as two threads and as two processes, and a `reap` during both | Each has its own lease file and lock; `reap` contacts the backend for neither | Take one lock per owner |
| A backend that declares it cannot fence, released before `execute` with an empty listing | Unconfirmed; the entry is kept until a listing taken after `late_arrival_s` is empty | Clear the entry on the first empty listing |
| A backend with no endpoint | Never "unreachable": `admit` is called | Treat a missing endpoint as unreachable |
| An endpoint given as a name that does not resolve; as a name that resolves to a closed port | "Unreachable" in both cases, decided by the driver; the backend made no network call | Let the backend resolve |
| Lifetime arithmetic with numbers | `lifetime_sufficient` is true at exactly floor plus the whole budget and false one second under; `lifetime_at_floor` is true at the floor and false one second under | Omit the wait, or the allowance, from the sum |
| An admission that completes on the far side **after** the kill by lease id was acknowledged (the conformance suite, against a fake that allocates late) | Nothing is listed for that lease afterwards and `execute` for it is refused; a fake that keeps the late allocation is rejected by the suite | Confirm by an empty listing alone |
| The conformance suite against this plan's fakes | Passes for the conformant fakes; fails, with the obligation named, for a fake that ignores `must_end_within_s`, one that ignores a bound, one that lists without lease ids or omits reservations, one that does not fence, and one that leaves something after refusing in `admit` | Run the suite only against conformant fakes |
| `renew` that never returns | The heartbeat gives up within its bound; the leg is not blocked by it | Call `renew` without a bound |
| A backend whose `admit`, `commit`, `kill`, `list_owned` never return and ignore their bound | The driver gives up on each at its bound; a cancel during each returns within the bound | Wait without a timeout |
| Existing call forms | `commit` with two arguments, `release` with one and `register_backend` with two still work | Make a new parameter required |
| After `execute`: a result that does not echo the request digest; `wait` raises; the connection is lost | No `completed` receipt; `sandbox_placement_lost_after_launch`; no call on any other rung | Try the next rung after a post-launch failure |
| After `execute`: `must_end_within_s` reached while the fake keeps reporting progress; a renewal arrives just before | The driver cancels and the leg ends `sandbox_placement_end_reached`; the renewal did not move the end | Extend on renewal |
| After `execute`: result received, then kill unconfirmed; no result, kill unconfirmed | Result kept with `sandbox_placement_release_unconfirmed`, entry remains; `sandbox_placement_lost_after_launch`, entry remains | Discard the result |
| `qualification` request while the flag is false | Driven; its receipts are marked and `applied_rule` is false for them | Count them as applied |
| A no-deadline leg on a backend with a maximum lifetime | Admitted and renewed while the lock is held | Refuse when `deadline_s is None` |
| Owner killed with SIGKILL between `commit` returning and the ref being recorded, while a second leg of the same owner is committing | `reap` kills the first leg's sandbox, found by its lease id, and leaves the second | Decide by `sandbox_ref` presence; liveness by pid |
| A lease entry kept after an unconfirmed release, at the next `reap` | The backend is asked again by lease id; the entry is cleared only when the kill is acknowledged and nothing is listed | Clear a kept entry after one attempt |
| Another owner's sandbox; a paused sandbox on the second page | Survives; reaped | Drop the owner filter; first page only |
| `reap` with an empty lease directory, and with only live leases | Zero backend calls, no plugin import | Call `list_owned` unconditionally |
| A root written with userinfo and a query | `request.root` holds neither | Pass the configured text |
| Every placement code | A member of `_HARNESS_DETAIL_CODES` with a `NOTICES` row whose fix is non-empty; `_exception_failure` on each returns the code, not the unknown-failure template | Remove a row |
| Flag-off behaviour | Every existing test in `tests/test_sandbox_placement.py` passes unchanged in substance | Call a backend from `_default_spawn` |

## Acceptance criteria
- [ ] **The table is total and is the reviewed one:** `LADDER_TABLE` has exactly one row
  for every state and event of C7's alphabet and no other, and equals the test's literal
  copy of C7's tables.
- [ ] **The model-based test passes:** for every transition of the state graph (one, two
  and three remote rungs, either last rung, built until no new state appears), the real
  `place`, driven through an ordering that contains it by fakes scripted to those events,
  produces the outcome, trail, backend calls and lease entries the reference gives; P1 to
  P14, I1 and I2 hold on every reference state and every real run, and L1 on the graph.
- [ ] **Each mutation in the mutation table turns that test red**, and the log of each is
  in the pull request.
- [ ] With fake backends, `place` then `run_placed` yield runtime-attested `committed` and
  `completed` receipts for one `sandbox_ref` and the computed digest, with the lease entry
  fsynced before `admit`; a workload still reporting progress at `must_end_within_s` is
  ended by the driver whatever renewals arrived; and the conformance suite rejects each
  fake built to break a backend obligation, the late allocation after a kill among them.
- [ ] `_NONLOCAL_EXECUTION_DRIVER` is still false, and the existing flag-off tests in
  `tests/test_sandbox_placement.py` pass.
## Maintainer decisions

**Rulings of 2026-10-10** (relayed by the team lead; each was asked with options):

| Ruling | Where it lands |
|---|---|
| Route: a self-hosted compute host over SSH first; the cloud backend follows as overflow | The order of the follow-on plans; the cloud backend is one more rung |
| Busy or down (B3): at the cap, wait a bounded time, then not run, never local. Unreachable before launch: run locally with a loud typed record. A started seat never moves. | C7: the capacity bar; the "unreachable" class; `execute` is final |
| A reachable host that refuses for a reason other than being full: "Eventually we will have a fallback ladder for different machines or to E2B. For now the local fallback is fine but leave the route to a more robust fallback / routing option open." | C7: a refused rung is left for the next; the last rung is a value whose default is the launching host |
| Credentials: expiring subscription tokens only; the renewal token never leaves the launching host; an API-key login or a stored long-lived seat token is refused for placement and the seat runs locally; no cap on a token's lifetime; a floor of 30 minutes of remaining life, in configuration, checked at the last moment before the credential is sealed into the request; refreshing a token inside a running seat is a named follow-on | C7 gives the rule its place: the preflight once, before the walk, against the floor plus the whole budget; the last-moment check is the guard in the sealing step. The credential details are the placed-seat plans'. |
| Dropped connection (Q1): the far end keeps a started seat alive for a limited time and the launching host resumes it, tied to that run; the time is a setting with a default of about 30 minutes | C12's invariants; built by the reconnect follow-on plan |
| Signed attestation (Q3): deferred, not dropped; required before any gate relies on a far end's claims and before the cloud backend | The RD4 row of the supersession table |
| Accounts (B6): one shared account first, superseding RD1 (a) for the SSH work | The follow-on plans; RD3 legs (ii) is kept because of it |
| The built-in egress list is left as it is | C5 neither changes nor relies on it |
| Access (B5), default (B2), scope (B4) | The follow-on plans; RD3 stands |

**Two rules here are the team lead's reading of those rulings, not rulings themselves.**
Each is written into the tables, can be changed in one row, and is put to the maintainer
below: a full rung may fall to another **remote** rung, never to the launching host (Q4);
and before `execute`, a rung whose release cannot be confirmed is left with a loud record
and a fenced, kept lease entry, and the walk goes on (Q5).

**Open: two questions for the maintainer.** Neither blocks this plan, which changes no
behaviour. With one remote rung, which is all the SSH work configures, both answers to Q4
behave the same; the answers to Q5 do not, so Q5 should be ruled before the flag turns on.

| ID | Question | Options | Built until ruled |
|---|---|---|---|
| Q4 | When a compute host is full and a second remote rung exists (another machine, or the cloud backend), may the seat try it? | (a) Yes: capacity on one remote rung may fall to another remote rung, never to the launching host. (b) No: a full rung ends the attempt, whatever else is configured. Simpler; a full host then never causes cloud spend. If (a): should the walk try the other remote rungs **before** it spends the wait on the full one? As built it waits first, on the rung that was full. | (a), waiting first. Changing either is one row of a table. |
| Q5 | Before a seat has been started on a compute host, that host stops answering, and the walk cannot confirm that what it reserved there is gone (the kill, or its confirmation, fails or times out). Does the seat still run somewhere? | (a) Yes, the walk goes on: to the next remote rung, or to the launching host. The rung is recorded loudly, its lease is fenced so that nothing can ever be started on it, and its entry is kept so that a later reaper finishes the kill. Cost: a slot and a copy of the staged tree may stay reserved on that host until then, while the seat runs elsewhere. No credential and no workload were sent there. (b) No: the attempt ends not run. Nothing of a seat ever runs while something of it may be held elsewhere, which is simpler to account for. Cost: a host that accepts connections and then goes silent costs every board its placed seats until someone repairs it. (c) Only to another remote rung, never to the launching host: the seat is not run unless another compute host takes it. Keeps load off the launching host while a compute host is in an unknown state. | (a). With one remote rung, (b) and (c) behave the same and (a) differs from both. Changing it is one row of the third table. |
Standing rulings this plan relies on, cited and not restated: R1 and R2
(agent-harness#1245); RD3, RD4, RD6 and CD1–CD4 (agent-harness#1162).

## Execution Policy

- execute: effort=high, reason=the contract every later plan and backend is held to; no launch-site change, but the admission and lease rules decide where a seat may run
