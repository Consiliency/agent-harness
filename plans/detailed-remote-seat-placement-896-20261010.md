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
| "The chain", step 3 (host-native fill) after a remote refusal | **Amended.** A seat whose walk ends on the launching host continues down this chain from the local sandbox as before. A seat under the capacity bar does not end on the launching host: it is not run, and is not filled natively there, which is as local as the local sandbox. |
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
  - `ExecutingBackend.admit(request, bound)` then sends the admission request. It raises
    `PlacementUnavailable(code)`. It is called after both revalidations and before
    `commit`. `available()` keeps its meaning: a local precondition, no network.
- **C4 Every blocking call is bounded and interruptible.** `admit`, `commit`, `execute`,
  `renew`, `cancel`, `kill`, `list_owned` and `release` take an `OperationBound(timeout_s,
  cancelled)`. A backend returns, or raises `sandbox_placement_operation_timeout`, within
  the bound, and checks `cancelled` while it waits. Every parameter and field this plan
  adds to an existing signature (`commit`, `release`, `register_backend`,
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
    never sends `execute` for a lease it has abandoned.
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
  ladder is a restatement of the two tables below. A model of them was enumerated over
  every event ordering for one, two and three rungs before this text was written; an
  implementation is accepted against the same enumeration (see "Verification").
  - **Rungs.** The configured remote backends, in the order agent-harness#1246's
    configuration already defines. After them one **last rung**, passed to the walk as a
    value: `local` (the launching host; the default of `PHASE_LOOP_SANDBOX_LAST_RUNG`) or
    `none`. The fail-closed knob forces `none`, and unlike the setting it also refuses legs
    that were never candidates, as it does today. A later ruling that wants another kind
    of last rung adds a value to that one setting and a branch where the walk resolves it;
    a second compute host or the cloud backend needs neither, being one more remote rung.
  - **Before the walk.** A leg that is not a placement candidate is not on the ladder. For
    a candidate the caller's **preflight** runs **once**, on facts the launching host
    already has. If it fails, no remote rung is tried and the walk resolves the last rung
    at once with the preflight's code.
  - **The budget.** When the preflight passes the walk gets one budget of time: the
    admission wait (`PHASE_LOOP_SANDBOX_ADMIT_WAIT_S`, default 600) plus the transfer
    allowance (`PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S`, default 300). Two events come
    from it. **Wait spent:** the time spent waiting at capacity, summed over all rungs,
    has reached the admission wait. **Budget spent:** the time since the walk began has
    reached the whole budget. Every call on a rung is bounded by what is left of the
    budget, except a release, which has its own bound outside it so that leaving a rung
    is always possible.
  - **The lifetime arithmetic is the driver's.** `lifetime_sufficient(remaining_s,
    floor_s)`, used once by the preflight, is true when `remaining_s` is at least the
    floor plus the **whole** budget. `lifetime_at_floor(remaining_s, floor_s)` is the
    guard in the sealing step, on fresh numbers. Because the walk cannot outlast the
    budget, a credential that passed the first still passes the second on whichever rung
    seals. Nothing re-runs the first after time has passed.

  **States of the rung in hand, and what moves it.** "Left" means the rung is finished
  with that class, a record is added to the trail, and the walk goes on as the second
  table says.

  | State | Event | Next | What it means |
  |---|---|---|---|
  | start | a local check fails: no backend is registered for the root's scheme or its plugin does not load, `available()` is false, `endpoint` raises, a required capability is not declared, the deadline exceeds the backend's maximum lifetime, a `leg` workload while the driver flag is false | left: **failed locally** | Nothing was sent |
  | start | the local checks pass | connecting | |
  | connecting | the driver's own resolution or connection fails | left: **unreachable** | Nothing was sent |
  | connecting | connected, but the lease entry cannot be written | left: **failed locally** | Nothing was sent |
  | connecting | budget spent | left: **out of time** | Nothing was sent. Running out of time is not evidence that the host is unreachable |
  | connecting | connected, lease entry fsynced | admitting | The admission request is sent |
  | admitting | admitted | committing | A slot is held on the far side |
  | admitting | the backend raises the runtime's capacity code | waiting | **The capacity bar is set for the attempt.** The far end's answer means it holds nothing. |
  | admitting | any other code | left: **refused** | The far end's own refusal means it holds nothing; the lease entry is cleared |
  | admitting | time-out, or the answer is lost | releasing | Something may be held |
  | admitting | budget spent | releasing | The request is abandoned in flight; something may be held |
  | waiting | back-off elapsed | admitting | The admission request is sent again |
  | waiting | wait spent, or budget spent | left: **capacity** | |
  | committing | committed, digest equal, required capabilities verified | sealing | |
  | committing | the transfer fails or times out, a capability is not verified, or budget spent | releasing | |
  | sealing | the caller's seal step returns the request (its guard passed) | **`execute` is called** | Final: the attempt is **placed** |
  | sealing | the guard fails, or sealing raises | releasing | |
  | releasing | the kill by lease id is acknowledged and `list_owned` shows nothing for it | left: **refused** | The lease entry is cleared |
  | releasing | the kill or the confirmation times out or fails | left: **refused, unconfirmed** | `sandbox_placement_release_unconfirmed` is recorded; **the lease entry is kept for the reaper; the lease stays fenced** (C6) |

  Entering "releasing" always fences the lease first.

  **The code recorded for each class**, so that every code in this plan's list is emitted
  by a transition:

  | Class | Code in the trail |
  |---|---|
  | failed locally | `sandbox_placement_driver_unavailable` (flag off); `sandbox_placement_capability_unmet` (a required capability not declared); `sandbox_placement_backend_unregistered`, `sandbox_placement_plugin_unavailable` or `sandbox_placement_refused` for the other local checks, as the seam raises them today |
  | unreachable | `sandbox_placement_unreachable` |
  | out of time | `sandbox_placement_budget_spent` |
  | capacity | `sandbox_placement_at_capacity` |
  | refused | The code the backend raised, if it is one of the runtime's (`sandbox_placement_not_enrolled`, `sandbox_placement_identity_mismatch`, `sandbox_placement_workload_unsupported`) or one it registered; `sandbox_placement_code_invalid` if it is neither; `sandbox_placement_operation_timeout` for a time-out; `sandbox_placement_capability_unmet` for a capability not verified after `commit`; `sandbox_placement_ref_invalid` or `sandbox_placement_capability_undeclared` for a bad reference or claim from `commit`, as the seam raises them today; `sandbox_placement_refused` for a failed transfer or guard |
  | refused, unconfirmed | The refusal's code, and `sandbox_placement_release_unconfirmed` beside it |

  **Cancel** is accepted in every state and **never moves the walk on**. In start,
  connecting and waiting the attempt ends at once. In admitting, committing and sealing
  the lease is fenced and released under the release's own bound, and then the attempt
  ends, whether or not the release was confirmed. In releasing the release in flight is
  finished and the attempt ends. The attempt's outcome is **cancelled**; `place` raises
  what main raises for a cancelled review operation, with the trail so far attached.

  **After a rung is left** (and no cancel is pending):

  | Condition | The walk |
  |---|---|
  | Another remote rung exists and the budget is not spent | Starts that rung |
  | Otherwise, the last rung is `local` and the capacity bar is not set | Ends on **the launching host** |
  | Otherwise, the last rung is `local` and the capacity bar is set | Ends **not run**, `sandbox_placement_capacity_exhausted` |
  | Otherwise (the last rung is `none`) | Ends **not run**, with the code of the last rung left, or `sandbox_placement_required_unavailable` under the knob |

  What follows from the tables, stated once each because a ruling or a reviewer asked:
  - **A seat is never run twice and never moves after `execute`.** `execute` is reached
    from one state and ends the walk.
  - **A full host never sends load to the launching host.** The capacity bar is set by the
    first capacity answer on any rung and nothing clears it. Under it a later remote rung
    may still take the seat (question Q4).
  - **Before `execute`, a rung that cannot be released with confirmation does not end the
    attempt.** Nothing ran there and no credential was sent, so going on cannot run the
    seat twice; the fence and the kept lease entry are what deal with whatever was left.
  - **Capacity is the runtime's word.** There is one capacity code and it is the runtime's
    (`sandbox_placement_at_capacity`). A backend answers capacity only by raising it; any
    other code, registered or not, is a refusal. Which of its own conditions a backend
    reports as capacity is fixed in that backend's plan; the driver cannot check that
    choice.
  - **Every exit carries the trail:** for each rung, in order, its name, its class and its
    code. It is returned with "placed", with "the launching host" and with "not run", and
    attached to what a cancel raises. A decision that ends on the launching host also
    carries the mark that the local route must be a tooled one (a seat that was a
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
  checks of C7's first row, in `place`, not left to its callers. A backend that cannot run a
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

These follow from the rulings as recorded. None is hidden in a table.

- **A broken, misconfigured or hung compute host sends its seats back to the launching
  host.** Unreachable, another build installed there, a revoked key, a failed host check, a
  host that accepts the connection and then stops answering: each is a typed notice with
  its fix line, and then the seat runs on the launching host. That is the ruling ("for now
  the local fallback is fine"). A compute host that is quietly broken for everyone
  therefore puts the whole load back where it started, with notices on every board and
  nothing else to stop it.
- **The capacity rule is the only thing that holds load off the launching host, and it
  works only when the compute host manages to say "full".** A host that is overloaded but
  answers with any other code, times out, or stops answering sends its load to the
  launching host. Which conditions a backend reports as capacity (its seat cap; its disk
  floor) is decided in that backend's plan, and the driver cannot check it.
- **One "full" answer bars the launching host for the whole attempt.** If the same rung
  then admits the seat and the transfer fails for an unrelated reason, the seat is not
  run, where without that answer it would have run on the launching host.
- **A slow rung can starve a healthy one.** The walk has one budget. If the first remote
  rung uses it up, a second remote rung is never asked.
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
  whole budget: a login that would have been long enough at the start may no longer be.
  A seat whose local route is the sealed one is not run.
- **A full compute host costs a board its placed seats.** They wait, once, for the
  admission wait, and are then not run. A board that needs those seats to reach its quorum
  does not reach it.
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
  `list_owned` and `kill` by lease (C3, C4, C6).
- `PLACEMENT_CODES` and `register_backend(scheme, backend, codes)` — add / modify — the
  runtime's closed code list, including the one capacity code, and registration of a
  backend's own codes, which only supply fix lines (C7). The four codes the seam already
  raises are entered here.
- `LADDER_TABLE` — add — C7's two tables as data: states, events, next states. `place`
  is written against it, and the model-based test reads the same object.
- `PlacementDecision` and `place(rungs, last_rung, prepared, request_for, open_lease, *,
  preflight, seal, driver_enabled, cancelled)` — add — the walk of C7, with C3's
  connection attempt and C8's seal step. The flag is passed in, so `sandbox_placement`
  does not import the launch module. It ends in one of: placed (`execute` has been
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
  its entry, marked abandoned (C6). It records the lease id, the backend name, the sanitized root, the
  `sandbox_ref` once known, `created_at` and `confirmed_killed_at`. It never records
  request or result bytes.
- `Lease.heartbeat(...)` — add — renews on an interval and stops with the leg (C2).
- `reap(backends, bound)` — add — driven by the journal: a backend is contacted only when
  an entry naming it exists with a free lock; with none, no call is made and no plugin is
  imported. For a contacted backend it applies C6's rule, confirms, then clears the entry.
  An entry whose lease the backend no longer lists **and whose kill it has acknowledged**
  is cleared; an abandoned entry is never cleared on an empty listing alone (C6). Liveness
  is never decided by pid or age.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `candidate_roots(...)` — add — the remote rungs: every configured non-local root, in the
  configured order. A root whose scheme has no registered backend, or whose plugin does not
  load, is still a rung; it fails its local checks (C7). No backend method is called and
  nothing is probed.
- `last_rung()` — add — reads `PHASE_LOOP_SANDBOX_LAST_RUNG`: `local` (default) or `none`;
  any other value is `sandbox_config_invalid`. The fail-closed knob forces `none`.
- `admit_wait_s()`, `transfer_allowance_s()` — add — the two settings, read with the
  `_env_int` idiom; defaults 600 and 300.

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
  nothing behind. It cannot observe what a backend on another machine puts in an
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
  admission wait, the transfer allowance); they have no effect until a backend exists and
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

**The ladder is tested from its table, not from a list of cases.**

`tests/test_placement_ladder_model.py` reads `LADDER_TABLE`, enumerates **every** event
ordering it allows for one, two and three remote rungs and for both values of the last
rung, and for each ordering:
1. scripts the fake backends, the loopback endpoints and a fake clock so that exactly those
   events happen, in that order;
2. drives the real `place`;
3. compares what `place` did with what the table says for that ordering: the outcome, the
   trail, the sequence of backend calls, and the lease journal's entries.

Then it asserts, on every ordering, the properties the rulings require:
- `execute` is called at most once, and exactly once when the outcome is "placed";
- no backend call follows `execute`;
- the outcome is never the launching host once any rung has answered at capacity;
- the outcome is "not run" only when the capacity bar is set or the last rung is `none`;
- after a cancel nothing happens except finishing a release already needed, and the
  outcome is "cancelled";
- whatever may still be held on a rung that was left has a lease entry and is fenced, and
  `execute` is never sent for a fenced lease;
- the trail names every rung that was touched, once, in order, on every kind of exit;
- no rung is started after the budget is spent.

The planning lane's model of the same table enumerated about 139 thousand orderings with
these assertions before this plan was written; the test asserts that no ordering is
skipped, not that number.

**Mutations of the product code, each of which must turn the model-based test red:**

| Mutation | The property it breaks |
|---|---|
| A non-capacity refusal ends the attempt instead of leaving the rung | "Not run" without the capacity bar |
| The capacity bar is cleared by a later admission, or not set at all | The launching host after a capacity answer |
| A cancel moves on to the next rung | Something other than a release after a cancel |
| An unconfirmed release clears the lease entry, or does not fence | Something held with no fenced lease entry |
| An unconfirmed release before `execute` ends the attempt | "Not run" without the capacity bar |
| The walk continues after `execute` | A backend call after `execute` |
| A rung is left without a trail record | The trail does not name every rung |
| The preflight's sum is evaluated again before a later rung | The table's outcome for the two-rung boundary ordering below |

**Named orderings.** Each is one ordering of the enumeration, kept as a test of its own so
that a failure reads as the finding it answers.

| Ordering | The table gives |
|---|---|
| Two remote rungs both refuse for a reason other than capacity; the last rung is `local` | The launching host, with both rungs in the trail |
| With the defaults: the credential has exactly 2700 seconds left (floor plus the whole budget); rung one is at capacity until the wait is spent, 600 seconds later; rung two admits and commits; the seal step sees 2100 seconds, which is above the 1800-second floor | Placed on rung two. One second less at the start: the launching host, nothing sent. |
| Connected; `admit` times out; the kill by lease id times out too (a host that accepts connections and then stops answering) | The rung is left "refused, unconfirmed" with `sandbox_placement_release_unconfirmed`, the lease entry kept and fenced; the walk goes on to the next rung, or to the launching host |
| At capacity, then admitted on the same rung, then the seal step's guard fails | Released; the capacity bar is set, so the next remote rung or "not run"; never the launching host |
| The budget is spent while rung one is committing | Rung one is released under the release's own bound; rung two is not started; the last rung is resolved |
| Cancel while an admission is in flight; while committing; while waiting; while releasing | "Cancelled" in each; the lease is fenced and released where anything may be held; no later `admit`, `commit` or `execute` on any rung; what is raised carries the trail |
| The first rung is unreachable and the second places the seat | "Placed", and the trail still shows why the first rung was left |
| A `leg` workload with the driver flag false | Every remote rung is left "failed locally" with `sandbox_placement_driver_unavailable`; the last rung is resolved; zero connection attempts |
| The preflight fails | The last rung is resolved at once with the preflight's code; zero connection attempts |
| Any ordering that ends on the launching host for a candidate seat | The decision carries the "never sealed" mark |

**The rest of the contract.**

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| `admit` raises: the runtime's capacity code; a code the backend registered; an unregistered code, prose, a path, 200 characters | Waiting; a refused rung; a refused rung recorded as `sandbox_placement_code_invalid`, the text appearing in no record or log | Treat a registered code as capacity; record `str(exc.reason)` |
| A backend with no endpoint | Never "unreachable": `admit` is called | Treat a missing endpoint as unreachable |
| An endpoint given as a name that does not resolve; as a name that resolves to a closed port | "Unreachable" in both cases, decided by the driver; the backend made no network call | Let the backend resolve |
| Lifetime arithmetic with numbers | `lifetime_sufficient` is true at exactly floor plus the whole budget and false one second under; `lifetime_at_floor` is true at the floor and false one second under | Omit the wait, or the allowance, from the sum |
| An admission that completes on the far side **after** the kill by lease id was acknowledged (the conformance suite, against a fake that allocates late) | Nothing is listed for that lease afterwards and `execute` for it is refused; a fake that keeps the late allocation is rejected by the suite | Confirm by an empty listing alone |
| The conformance suite against this plan's fakes | Passes for the conformant fakes; fails, with the obligation named, for a fake that ignores `must_end_within_s`, one that ignores a bound, one that lists without lease ids or omits reservations, one that does not fence, and one that leaves something after refusing in `admit` | Run the suite only against conformant fakes |
| `renew` that never returns | The heartbeat gives up within its bound; the leg is not blocked by it | Call `renew` without a bound |
| A backend whose `admit`, `commit`, `kill`, `list_owned` never return | Each ends within its bound; a cancel during each returns within the bound | Wait without a timeout |
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
- [ ] **The model-based test passes:** for every event ordering `LADDER_TABLE` allows with
  one, two and three remote rungs and either last rung, the real `place`, driven by fakes
  scripted to that ordering, produces the outcome, trail, backend calls and lease entries
  the table gives, and every property listed under "Verification" holds.
- [ ] **Each mutation in the mutation table turns that test red**, and the log of each is
  in the pull request.
- [ ] The trail is present and complete on every kind of exit: placed (including on a
  later rung), the launching host, not run, and attached to what a cancel raises; removing
  it from any one of those exits turns a named test red.
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
They are written into the table and can each be changed in one row.
- A full rung may fall to another **remote** rung, never to the launching host (question
  Q4, below).
- Before `execute`, a rung that cannot be released with confirmation is left with a loud
  record and a fenced, kept lease entry, and the walk goes on. This follows "for now the
  local fallback is fine": nothing ran there, so going on cannot run the seat twice.

**Open: one question for the maintainer.** It does not block this plan: with one remote
rung, which is all the SSH work configures, both answers behave the same.

| ID | Question | Options | Built until ruled |
|---|---|---|---|
| Q4 | When a compute host is full and a second remote rung exists (another machine, or the cloud backend), may the seat try it? | (a) Yes: capacity on one remote rung may fall to another remote rung, never to the launching host. (b) No: a full rung ends the attempt, whatever else is configured. Simpler; a full host then never causes cloud spend. If (a): should the walk try the other remote rungs **before** it spends the wait on the full one? As built it waits first, on the rung that was full. | (a), waiting first. Changing either is one row of the table and its orderings. |

Standing rulings this plan relies on, cited and not restated: R1 and R2
(agent-harness#1245); RD3, RD4, RD6 and CD1–CD4 (agent-harness#1162).

## Execution Policy

- execute: effort=high, reason=the contract every later plan and backend is held to; no launch-site change, but the admission and lease rules decide where a seat may run
