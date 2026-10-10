---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1246, agent-harness#1162, agent-harness#1165, agent-harness#1245, agent-harness#1222, agent-harness#1166, agent-harness#1253, agent-harness#1170]
amends: [plans/detailed-remote-sandbox-placement-896-20260929.md, plans/detailed-e2b-cloud-backend-896-20260929.md, plans/detailed-1244-seat-route-resolver-20261004.md]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_seat_notices.py tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_panel_leg_status_detail_1096.py tests/test_launchspec_golden.py"
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
| "The chain", order of steps 1 and 2 | **Amended for a host with a remote root configured:** the remote rungs of C7's ladder are tried first, in the configured order. The local sandbox is the ladder's last rung. |
| "The chain", step 3 (host-native fill) after a remote refusal | **Amended.** A seat that reaches the last rung continues down this chain from the local sandbox as before. A seat that left a rung for capacity never reaches the last rung: it is not run, and is not filled natively on the launching host, which is as local as the local sandbox. |
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
    deadline, a leg whose deadline exceeds `declaration().max_lifetime_s` is refused before
    `commit`. Without one, the driver renews while, and only while, the owning process
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
    `sandbox_policy.probe_timeout_s()`, and closes it. A failure of the resolution or of
    the connection is "unreachable", and nothing else is: an exception from `endpoint`
    itself is a refusal (C7, row 0), and a backend with no endpoint is never
    "unreachable".
  - `ExecutingBackend.admit(request, bound)` then sends the admission request. It raises
    `PlacementUnavailable(code)`. It is called after both revalidations and before
    `commit`. `available()` keeps its meaning: a local precondition, no network.
- **C4 Every blocking call is bounded and interruptible.** `admit`, `commit`, `execute`,
  `renew`, `cancel`, `kill`, `list_owned` and `release` take an `OperationBound(timeout_s,
  cancelled)`. Every parameter and field this plan adds to an existing signature
  (`commit`, `release`, `register_backend`, `PlacementRequest`) has a default, because the
  launch site and the flag-off tests still call them in today's form. A backend returns, or raises `sandbox_placement_operation_timeout`, within
  the bound, and checks `cancelled` while it waits. These bounds are separate from a
  seat's thinking time: `wait(sandbox_ref, wait_s)` returns an `ExecResult`, or an
  `ExecProgress(sandbox_ref, seq)` whose rising `seq` is a liveness claim for the review
  monitor and nothing else.
- **C5 Required capabilities, and no private endpoint for a placed seat.**
  `PlacementRequest.required_capabilities` for a review leg is `inbound_closed`,
  `one_shot_secret_channel` and `private_ranges_unreachable`. `egress_needs` is **empty**
  for every non-local candidate: the launching host's built-in list describes the launching
  host's own namespace and is not a need of the leg. A backend builds a placed seat's
  namespace with an empty private allowlist. The driver refuses before `admit` if the
  required set is not within `capabilities()`, and after `commit`, before `execute`, if it
  is not within `verified`.
- **C6 Owner, lease and root travel with the request.** `PlacementRequest` carries `root`
  (the parsed, sanitized location and the configured backend name: the form
  `sandbox_policy.parse_location` already produces, so userinfo, query and fragment never
  reach a backend), `owner_id` and `lease_id`.
  - The lease id is allocated and its journal entry fsynced **before `admit`**, the first
    call with a remote effect. On a ladder each rung that is asked gets its own lease.
  - A backend tags every sandbox it creates with the owner id and the lease id.
    `list_owned(owner_id, bound)` returns `(sandbox_ref, lease_id)` pairs;
    `kill(sandbox_ref, lease_id, bound)` is targeted.
  - The reaper decides by lease: it kills a listed sandbox only when that lease's lock is
    free. An owner that died between `commit` and recording its `sandbox_ref` is therefore
    still found, and a live leg of the same owner in that window is never killed.
  - The reaper runs at leg start and by command. A periodic reaper is not built: no backend
    planned so far bills by time. The cloud adapter adds one if it needs one.
- **C7 Where a seat may run: a ladder, walked by the driver** (maintainer rulings of
  2026-10-10 on "busy or down" and on a reachable host that refuses).
  - **The rungs.** The configured remote backends, in the order agent-harness#1246's
    configuration already defines, then one **last rung** named by a setting.
    `PHASE_LOOP_SANDBOX_LAST_RUNG` is `local` (the default: the launching host) or `none`.
    The driver does not know that the last rung is special beyond that setting, so a later
    ruling can replace it, or remove it, without changing the driver. The fail-closed knob
    means `none`.
  - **The driver classifies what happened on a rung itself.** Nothing a backend or a far
    end says chooses the class: "unreachable" is the driver's own connection attempt (C3);
    "at capacity" is a code the backend registered as such when it was installed;
    everything else before `execute` is "refused".

  | # | On a remote rung | The driver does | Then |
  |---|---|---|---|
  | 0 | The rung fails on the launching host before anything is sent: `available()` is false; `endpoint` raises; a required capability is not in `capabilities()`; the leg's deadline exceeds the backend's `max_lifetime_s`; the lease entry cannot be written; the driver flag is false and the workload is a `leg` | Records `refused` with the typed code. Nothing was sent, so there is nothing to release. | Next rung |
  | 1 | The driver's own connection attempt fails | Records `unreachable` for the rung. Nothing was sent, so there is nothing to release. | Next rung |
  | 2 | The rung answers **at capacity** | Retries on **that** rung, with backoff, while the seat's admission wait lasts (`PHASE_LOOP_SANDBOX_ADMIT_WAIT_S`, default 600, `0` means no wait; one wait per seat, not per rung: see "One budget"). If it is admitted, row 4. If it is still full, records `capacity` for the rung. | Next **remote** rung. From the first capacity answer on, **the last rung is barred for this attempt** when it is the launching host. |
  | 3 | Anything else before `execute`: not enrolled; the host is not the one pinned; any other refusal by the far end (another build installed there, its own checks failed, out of disk); a required capability declared but not verified after `commit`; a transfer failure; an operation timeout; **the caller's guard immediately before sealing fails** | Records `refused` with the typed code and its fix line. **Releases anything held on that rung and confirms it is gone** (C8). | Next rung. If the release cannot be confirmed, the attempt ends **not run** (`sandbox_placement_rung_unconfirmed`): the seat does not move on while something of it may still exist behind it. |
  | 4 | Admitted, committed, the guard passes, `execute` is called | **Placed.** | Final. The seat never moves and is never started again, on any rung, whatever happens after (C12 governs a lost connection). |

  | # | Reaching the last rung | Outcome |
  |---|---|---|
  | 5 | The last rung is `local` and no rung answered at capacity | **Runs on the launching host**, with the loud record below. The local route is decided from the local host's facts; **if that route is the sealed one the seat is not run**. |
  | 6 | The last rung is `local` but a rung answered at capacity | **Not run**, `sandbox_placement_capacity_exhausted`. A full compute host never pushes load back to the launching host. |
  | 7 | The last rung is `none` (or the fail-closed knob is on) | **Not run**, with the code of the last rung left, or `sandbox_placement_required_unavailable` under the knob |

  - **The decision says "never sealed".** A decision that ends on the launching host for a
    seat that was a placement candidate carries a mark that the local route must be a
    tooled one. This plan sets and tests the mark; the plan that wires the launch site
    honours it.
  - **Before the ladder.** A leg that is not a placement candidate is not on the ladder and
    runs as today. For a candidate the caller's **preflight** runs before the first
    admission request, on facts the launching host already has (examples the follow-on
    plans add: the launching runtime is a source checkout and not a released build; the
    credential is not a kind that may be placed; its remaining life is too short). A seat
    that fails it skips every remote rung and goes straight to the last rung with the
    preflight's typed code. Nothing is sent anywhere for it.
  - **One budget for the whole walk.** When the preflight passes, the driver fixes one
    placement budget for the attempt: the admission-wait bound plus
    `PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S` (default 300). Every rung lives inside it: its
    connection attempt, its `admit` round trips, its wait at the cap, its `commit`, and any
    release. The wait is therefore one budget per seat, shared by all rungs, not one per
    rung, and `commit` is bounded by what is left. When the budget is spent before
    `execute`, the rung in hand is left as row 3, the remaining remote rungs are skipped,
    and the walk goes to the last rung (rows 5 to 7).
  - **The lifetime arithmetic is the driver's,** so every caller uses the same sum:
    `lifetime_sufficient(remaining_s, floor_s)` is true when `remaining_s` is at least the
    floor plus the placement budget; `lifetime_at_floor(remaining_s, floor_s)` is the
    guard. A caller supplies only the two numbers. Because the walk cannot outlast the
    budget, a credential that passes the preflight still has its floor at the guard, on
    whichever rung that is. The guard stays on every rung as a check, and its failure is
    row 3. This plan tests both functions with numbers.
  - **A seat is never run twice.** `execute` is called at most once per attempt, on one
    rung. A rung is left only as row 0 or row 1 (nothing was sent), row 2 (the far end
    answered that it admitted nothing) or row 3 (a confirmed release, or the far end's own
    refusal).
  - **Every rung change is loud.** `place` returns the trail: for each rung, in order, its
    name, its class, its code. The trail is what the launch site puts into the board's
    output and the leg's machine-readable record (`sandbox_root_reason` carries each
    `<rung>: <code>`, as it does today for a single root); each code with a `NOTICES` row
    is a seat notice with its fix line; landing on the last rung adds
    `seat_sandbox_root_fell_back`. The wiring is the plan that turns the flag on; the
    trail, complete and in order, is this plan's. "Everything
    quietly ran locally" cannot happen.
  - **Where the decision sits.** Where `commit` is called today, after local staging and
    both revalidations. Nothing has been acquired for a placed launch at that point, so a
    seat that reaches the launching host continues from there exactly as today.
  - **Waiting.** While a seat waits at the cap the monitor record carries `placement_wait`,
    the notice `seat_placement_waiting` is shown, and the stall clock does not run. A leg's
    stall clock starts when `execute` returns: admission, the wait, the transfer and any
    rung change are not silence. For a bounded leg all of them are charged to its deadline,
    as the login wait is.
  - **Codes.** The runtime owns a closed list of placement codes. A backend registers its
    own codes when it is installed, each marked "capacity" or not; that static mark is all
    a backend contributes to the classes above. An unregistered code is recorded as
    `sandbox_placement_code_invalid`, never as backend text.
- **C8 A rung that is left is released, and the release is confirmed.** Once `admit` has
  been **called** on a rung, every way of leaving that rung without `execute` ends in a
  targeted `kill` by lease id and a confirmation through `list_owned` that nothing of this
  attempt remains: a failed `commit`, a failed guard, a spent budget, a cancel, and also an
  `admit` that timed out, was cancelled, or whose answer was lost, because the far end may
  have created something. The one exception is a refusal the far end itself returned from
  `admit`: that is its statement that it admitted nothing. The same holds after `place`
  has returned "placed": the decision is a context, and leaving it without `execute`
  having been called (the caller failed while building the request) releases the same
  way.
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
  driver itself refuses a `leg` request while the flag is false**, before any connection
  attempt: the guard is in `place`, not left to its callers. A backend that cannot run a
  workload refuses it in `admit` (`sandbox_placement_workload_unsupported`), so nothing is
  transferred for a workload that will not run. The flag turns on in the plan after which
  a real backend runs a seat end to end, not before.
- **C11 Confirmed release, and a finished review is kept.** `release` returns only when the
  sandbox is confirmed gone (`kill`, then absent from `list_owned`). If the result was
  already received and ingested, an unconfirmed kill does **not** discard it: the leg keeps
  its result, carries the notice `sandbox_placement_release_unconfirmed`, and the lease
  entry stays for the reaper. Without a result, an unconfirmed kill ends the leg with
  `sandbox_placement_lost_after_launch`.
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

- **A broken or misconfigured compute host sends its seats back to the launching host.**
  Unreachable, another build installed there, a revoked key, a failed host check, a full
  disk: each is a typed notice with its fix line, and then the seat runs on the launching
  host. That is the ruling ("for now the local fallback is fine"). It also means a compute
  host that is quietly broken for everyone puts the whole load back where it started, with
  notices on every board and nothing else to stop it.
- **The capacity rule is the only thing that holds load off the launching host.** A compute
  host that answers "full" makes seats wait and then not run. A compute host that answers
  anything else, or does not answer, does not.
- **The real floor for placement is 45 minutes of token life by default, not 30.** A seat
  is placed only if its credential outlasts the ruled floor (30 minutes) plus the placement
  budget (ten minutes of waiting and five of transfer by default). A token with between 30
  and 45 minutes left runs on the launching host. Raising the wait raises this number.
- **A placed seat is ended when its credential expires, even while it is working.** C2's
  end is the earliest of the leg's deadline and that expiry. Under heartbeat-only, where a
  local seat has no deadline and silence never ends it, a placed seat therefore has a hard
  limit equal to its token's remaining life, which can be as little as the floor; it is
  then lost and is not run again. A local seat is never started in order to be cut off
  this way. This takes effect only when the flag turns on; the plan that does that must
  amend the monitoring policy section of the contract and say this again.
- **"Unreachable" means the driver could not connect within its bound.** A compute host too
  loaded to accept a connection in that time is "unreachable", and its seats run on the
  launching host: the one way load can still spill back while the host is, in fact, busy.
- **A full compute host costs a board its placed seats.** They wait, once, for the budget,
  and are then not run. A board that needs those seats to reach its quorum does not reach
  it.
- **Boards run from a source checkout** (the usual way boards run in this repository) are
  never the build a compute host has installed. The SSH follow-on plan should make that a
  preflight failure, so those boards go straight to the last rung without a round trip.
- **One limit for the whole account** on the compute host. One seat's memory use can get
  another user's seat killed, and that seat is not run again.
- **Reaching the launching host does not always mean the review happens.** The local
  route's own rules apply there, and a seat whose local route is the sealed one is not run.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `PlacementRequest` — modify — optional deadline; `workload`, `required_capabilities`,
  `root`, `owner_id`, `lease_id`; `egress_needs` empty for a non-local candidate (C2, C5,
  C6, C10).
- `ExecSpec`, `ExecResult` — modify; `ExecProgress`, `OperationBound` — add (C1, C2, C4).
- `ExecutingBackend` — modify — `endpoint`, `admit`; the bound on each blocking call;
  `list_owned` and `kill` by lease (C3, C4, C6).
- `PLACEMENT_CODES` and `register_backend(scheme, backend, codes)` — add / modify — the
  runtime's closed code list, and registration of a backend's codes, each marked
  "capacity" or not (C7). The four codes the seam already raises are entered here.
- `PlacementDecision` and `place(rungs, last_rung, prepared, request_for, lease, *,
  preflight, guard, driver_enabled, bound)` — add — the C7 ladder, with C3's connection
  attempt, C8, and C10's refusal of a `leg` workload when `driver_enabled` is false. The
  flag is passed in, so `sandbox_placement` does not import the launch module. It returns
  one of: placed (a `LegPlacement`, which is a context per C8), the launching host (with
  the "never sealed" mark), or not run (with its code); and always the trail of rungs. It
  owns the placement budget.
- `lifetime_sufficient`, `lifetime_at_floor` — add — the two comparisons of C7, pure
  functions of two numbers and the two settings.
- `run_placed(placement, spec, *, on_progress, cancelled) -> ExecResult` — add — `execute`,
  the `wait` loop, renewal, cancel, C2's end and C11. After `execute` is called every exit
  is post-launch.
- `LegPlacement.record_runtime(step)` — add — the only builder of runtime `committed`,
  `launched` and `completed` receipts for a non-local placement (C9).

### `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` (create)
- `owner_id()` — add — a per-user random id under `state_home()/phase-loop/` (0600).
- `open_lease(backend_name, root) -> Lease` — add — allocates the lease id and writes one
  file under `state_home()/phase-loop/placement-leases/` (directory 0700, file 0600),
  fsynced with its directory before `admit`, held under `flock` by the owning process for
  the life of the leg. It records the lease id, the backend name, the sanitized root, the
  `sandbox_ref` once known, `created_at` and `confirmed_killed_at`. It never records
  request or result bytes.
- `Lease.heartbeat(...)` — add — renews on an interval and stops with the leg (C2).
- `reap(backends, bound)` — add — driven by the journal: a backend is contacted only when
  an entry naming it exists with a free lock; with none, no call is made and no plugin is
  imported. For a contacted backend it applies C6's rule, confirms, then clears the entry.
  An entry whose lease the backend no longer lists is cleared. Liveness is never decided by
  pid or age.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `candidate_roots(...)` — add — the remote rungs: every configured non-local candidate
  whose scheme has a registered backend, in the configured order. No backend method is
  called and nothing is probed.
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
  `sandbox_placement_release_unconfirmed`, `sandbox_placement_rung_unconfirmed`,
  `seat_placement_waiting`.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … A detail is one of: a HARNESS CODE — a
  fixed string this runtime itself emits (`_HARNESS_DETAIL_CODES`)". Members are added by
  that mechanism; no template or category is added.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `placement` command, action `reap` — add — runs `placement_lease.reap` for the configured
  backends. Its `dest`s are uniquely named.

### `phase-loop-runtime/tests/placement_backend_conformance.py` (create)
- A conformance suite, parametrised over a backend factory — add — the obligations this
  contract puts on a **backend**, which the driver's own tests can only check from the
  driver's side: the request is used only as C1 allows; the workload is ended at
  `must_end_within_s` with no further call from the driver (C2); every blocking call
  honours its bound and its cancel (C4); every sandbox is tagged, listed and killed by
  lease id (C6); a refusal from `admit` leaves nothing behind (C8). This plan runs it
  against its own fakes, including fakes built to violate each obligation, which it must
  reject. Every backend plan runs it against its backend.

### `phase-loop-runtime/tests/test_placement_driver.py`, `tests/test_placement_lease.py` (create); `tests/test_sandbox_placement.py`, `tests/test_seat_notices.py`, `tests/data/seat_launch_references.json`, `tests/test_agent_cli_scratch_inventory_1147.py` (modify)
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
  tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py \
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

**The C7 ladder, one row each, then its intersections.** The fakes are two remote rungs and
a last rung that the test sets to `local` or `none`. "Runs on the launching host" means
`place` returns that decision; the launch site is not changed by this plan.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Row 0, one case each: `available()` false; `endpoint` raises; a required capability undeclared; a deadline over `max_lifetime_s`; the lease entry cannot be written; a `leg` workload with the driver flag false | `refused` with its code in the trail; zero connection attempts and zero `admit` calls on that rung; next rung | Treat a local failure as unreachable |
| Row 0 then row 1: the first rung fails locally, the second endpoint is closed | Launching host, with both rungs in the trail under their own classes | Require every rung to have had a connection attempt |
| Row 1: both remote endpoints closed | Launching host; the trail shows two `unreachable` rungs; zero `admit` calls | Let a backend report "unreachable" from `admit` |
| Row 1 then row 4: first endpoint closed, second admits | Placed on the second; the trail shows why the first was left | Stop at the first rung |
| Row 2: at capacity, then admitted within the wait | Placed on that rung | Move on at the first capacity answer |
| Row 2 then row 6: at capacity, wait spent, no other remote rung | Not run, `sandbox_placement_capacity_exhausted`; the launching host is not used | Fall to the last rung |
| Row 2 across rungs: first rung at capacity (wait spent), second rung admits | Placed on the second rung | Stop the walk at the first capacity |
| Row 2 then row 1: first rung at capacity, second rung unreachable | Not run; the launching host is not used | Decide from the last rung's class |
| Row 2 then row 3: first rung at capacity, second rung refuses | Not run; the launching host is not used | The same |
| Row 3, one case per kind: not enrolled; identity mismatch; another registered refusal; a capability declared but not verified after `commit`; `commit` raises; operation timeout | `refused` with that code in the trail. Where `admit` had succeeded or its outcome is unknown, `release` is called and confirmed on that rung; where the far end refused in `admit`, none is needed and none is called. Then the next rung; with none left and the last rung `local`, the launching host | Skip the release; treat a refusal as capacity |
| Row 3: the guard fails immediately before sealing | Released and confirmed; `execute` never called; next rung, or the launching host | Call `execute` and let the far end refuse |
| Row 3, release cannot be confirmed | Not run, `sandbox_placement_rung_unconfirmed`; no further rung is tried | Move on anyway |
| **Intersection:** at capacity, then admitted on the same rung, then the guard fails | That rung is left as `refused`, released and confirmed; a capacity answer was seen, so the launching host is barred: next remote rung, or not run | Let a later refusal clear the capacity bar |
| Intersection: the first rung refuses (not capacity), the second is at capacity with the wait spent | Not run; the bar applies whichever rung set it | Bar the last rung only when the first rung was full |
| Row 4, then a failure after `execute` (raise, lost acknowledgement, `wait` raises, connection lost) | `sandbox_placement_lost_after_launch`; no `admit` or `execute` on any other rung afterwards | Try the next rung after a post-launch failure |
| Rows 5 and the preflight exit: the decision for a seat that was a candidate | Carries the "never sealed" mark; a decision for a leg that was never a candidate cannot be built with it | Omit the mark |
| An `admit` that creates a tagged sandbox and then times out; one that is cancelled; one whose answer is lost | The rung is left only after `kill` by lease id and a confirming `list_owned`; then the next rung | Move on without a call when `admit` did not return |
| The caller raises between `place` returning "placed" and `execute` | Leaving the decision's context kills by lease id and confirms; `execute` was never called | Leave the sandbox for the reaper |
| Row 7: the last rung is `none`; the fail-closed knob is on | Not run with the last rung's code; `sandbox_placement_required_unavailable`; zero spawns | Default to `local` when the setting is unreadable |
| The preflight fails before the ladder | Launching host with the preflight's code; zero connection attempts, zero backend calls | Run the preflight after `admit` |
| One budget: two remote rungs both at capacity | The total time waited across both is one admission-wait bound, not two; then not run | Give each rung its own wait |
| One budget: the first rung uses most of it and is left; the second rung's `commit` | Is bounded by what is left of the budget; when the budget is spent the rung is left as row 3 and no further remote rung is tried | Bound `commit` by the full allowance on every rung |
| Lifetime arithmetic with injected numbers and a fake clock: `lifetime_sufficient` at exactly floor + wait + allowance, and one second under; then the wait runs to its end and the transfer takes the whole allowance | True, false; `lifetime_at_floor` still true and the seat is placed | Omit the wait, or the allowance, from the sum |
| The trail | Every rung appears once, in order, with its class and code; the same list is what the caller is given to record; a walk that ends on the launching host can never return an empty trail | Return only the final decision |
| Never twice | Across every case above the fakes record at most one `execute` in total | — |

**The rest of the contract.**

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| A backend's `admit` raises a code registered to any outcome, an unregistered code, prose, a path, 200 characters | Never local; the unregistered ones are `sandbox_placement_code_invalid` and their text appears in no record or log | Record `str(exc.reason)` |
| A backend with no endpoint | Never "unreachable": `admit` is called, and its failures are row 3 | Treat a missing endpoint as unreachable |
| An endpoint given as a name that does not resolve; as a name that resolves to a closed port | "Unreachable" in both cases, decided by the driver; the backend made no network call | Let the backend resolve |
| `renew` that never returns | The heartbeat gives up within its bound; the leg is not blocked by it | Call `renew` without a bound |
| The conformance suite against this plan's fakes | Passes for the conformant fakes; fails, with the obligation named, for a fake that ignores `must_end_within_s`, one that ignores a bound, one that lists without lease ids, and one that leaves a sandbox after refusing in `admit` | Run the suite only against conformant fakes |
| Existing call forms | `commit` with two arguments, `release` with one and `register_backend` with two still work | Make a new parameter required |
| Result that does not echo the request digest | No `completed` receipt; `sandbox_placement_lost_after_launch` | Skip the echo check |
| `admit` succeeded, then `commit` raises or the guard fails | `release` is called on that candidate before anything else | Skip the release |
| A backend whose `admit`, `commit`, `kill`, `list_owned` never return | Each ends within its bound as `sandbox_placement_operation_timeout`; a cancel during each returns within the bound | Wait without a timeout |
| Cancel during the capacity wait | Zero backend calls after it | Sleep through cancel |
| `must_end_within_s` reached while the fake keeps reporting progress; a renewal arrives just before | The driver cancels and the leg ends `sandbox_placement_end_reached`; the renewal did not move the end | Extend on renewal |
| `qualification` request while the flag is false | Driven; its receipts are marked and `applied_rule` is false for them | Count them as applied |
| `place` called with a `leg` workload while the flag is false | Refused by `place` itself: zero connection attempts, zero backend calls | Check the flag in the caller only |
| No-deadline leg on a backend with `max_lifetime_s`; deadline beyond it | Admitted and renewed while the lock is held; refused before `commit` | Refuse when `deadline_s is None` |
| Owner killed with SIGKILL between `commit` returning and the ref being recorded, while a second leg of the same owner is committing | `reap` kills the first leg's sandbox, found by its lease id, and leaves the second | Decide by `sandbox_ref` presence; liveness by pid |
| Another owner's sandbox; a paused sandbox on the second page | Survives; reaped | Drop the owner filter; first page only |
| `reap` with an empty lease directory, and with only live leases | Zero backend calls, no plugin import | Call `list_owned` unconditionally |
| Result received, then kill unconfirmed; no result, kill unconfirmed | Result kept with `sandbox_placement_release_unconfirmed`, entry remains; `sandbox_placement_lost_after_launch`, entry remains | Discard the result |
| A root written with userinfo and a query | `request.root` holds neither | Pass the configured text |
| Every placement code | A member of `_HARNESS_DETAIL_CODES` with a `NOTICES` row whose fix is non-empty; `_exception_failure` on each returns the code, not the unknown-failure template | Remove a row |
| Flag-off behaviour | Every existing test in `tests/test_sandbox_placement.py` passes unchanged in substance | Call a backend from `_default_spawn` |

## Acceptance criteria
- [ ] Each row of the C7 ladder has a passing case, and the capacity bar holds in every
  order: once any rung has answered at capacity the launching host is never the outcome,
  whatever later rungs answer; without a capacity answer, a refusal or an unreachable rung
  ends on the launching host with a trail naming each rung and its code.
- [ ] A rung is left only with nothing sent, on the far end's own refusal, or after a
  confirmed release; when a release cannot be confirmed the attempt ends not run; the fakes
  record at most one `execute` per attempt in every case; and a rung's class is never
  chosen by a backend at run time ("unreachable" is only the driver's own connection
  attempt, "capacity" only a code registered as such at installation).
- [ ] With fake backends, `place` then `run_placed` yield runtime-attested `committed` and
  `completed` receipts for one `sandbox_ref` and the computed digest, with the lease entry
  fsynced before `admit`; an owner killed between `commit` and recording its ref has its
  sandbox reaped by lease id while a concurrent live leg of the same owner survives.
- [ ] A backend call that never returns ends within its bound, a cancel during it returns
  within the bound, a workload still reporting progress at `must_end_within_s` is ended by
  the driver with `sandbox_placement_end_reached` whatever renewals arrived, and the
  conformance suite rejects each fake built to break a backend obligation.
- [ ] `_NONLOCAL_EXECUTION_DRIVER` is still false, `place` itself refuses a `leg` workload
  while it is, and the existing flag-off tests in `tests/test_sandbox_placement.py` pass.

## Maintainer decisions

**Rulings of 2026-10-10** (relayed by the team lead; each was asked with options):

| Ruling | Where it lands |
|---|---|
| Route: a self-hosted compute host over SSH first; the cloud backend follows as overflow | The order of the follow-on plans; the cloud backend is one more rung |
| Busy or down (B3): at the cap, wait a bounded time, then not run, never local. Unreachable before launch: run locally with a loud typed record. A started seat never moves. | C7, rows 1, 2, 4 and 6 |
| A reachable host that refuses for a reason other than being full: "Eventually we will have a fallback ladder for different machines or to E2B. For now the local fallback is fine but leave the route to a more robust fallback / routing option open." | C7 as a ladder: row 3; the last rung is a setting whose default is the launching host |
| Credentials: expiring subscription tokens only; the renewal token never leaves the launching host; an API-key login or a stored long-lived seat token is refused for placement and the seat runs locally; no cap on a token's lifetime; a floor of 30 minutes of remaining life, in configuration, checked at the last moment before the credential is sealed into the request; refreshing a token inside a running seat is a named follow-on | C7 gives the rule its place: the preflight before the ladder and again before each rung; the last-moment check is the guard, row 3. The credential details are the placed-seat plans'. |
| Dropped connection (Q1): the far end keeps a started seat alive for a limited time and the launching host resumes it, tied to that run; the time is a setting with a default of about 30 minutes | C12's invariants; built by the reconnect follow-on plan |
| Signed attestation (Q3): deferred, not dropped; required before any gate relies on a far end's claims and before the cloud backend | The RD4 row of the supersession table |
| Accounts (B6): one shared account first, superseding RD1 (a) for the SSH work | The follow-on plans; RD3 legs (ii) is kept because of it |
| The built-in egress list is left as it is | C5 neither changes nor relies on it |
| Access (B5), default (B2), scope (B4) | The follow-on plans; RD3 stands |

**Open: one question for the maintainer.** It does not block this plan: with one remote
rung, which is all the SSH work configures, both answers behave the same.

| ID | Question | Options | Built until ruled |
|---|---|---|---|
| Q4 | When a compute host is full and a second remote rung exists (another machine, or the cloud backend), may the seat try it? | (a) Yes: capacity on one remote rung may fall to another remote rung, never to the launching host. This is the team lead's reading of the two rulings together. (b) No: a full rung ends the attempt, whatever else is configured. Simpler; a full host then never causes cloud spend. | (a). Changing to (b) is one line in the walk and one test row. |

Standing rulings this plan relies on, cited and not restated: R1 and R2
(agent-harness#1245); RD3, RD4, RD6 and CD1–CD4 (agent-harness#1162).

## Execution Policy

- execute: effort=high, reason=the contract every later plan and backend is held to; no launch-site change, but the admission and lease rules decide where a seat may run
