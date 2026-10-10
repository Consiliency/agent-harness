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
| "The chain", order of steps 1 and 2 | **Amended for a host with a remote root configured:** remote is tried first. The local sandbox is reached only by the rows of C7 that end in "local". |
| "The chain", step 3 (host-native fill) after a remote refusal | **Amended:** once an admission request has been sent, a seat that is not placed is not run. It is not filled natively on the launching host, which is as local as the local sandbox. |
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
  is bytes and travels **only** on the backend's one-shot channel; a backend never writes
  it to a file system, an environment or a log. `ExecResult` is
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
    reports `sandbox_placement_end_reached`.
- **C3 Reachability is the driver's; admission is the backend's.**
  - `ExecutingBackend.endpoint(root)` returns the address and port the backend would
    connect to, resolved locally with no network use, or `None` if it has no such endpoint.
  - **The driver itself** opens a connection to that endpoint, within a bound, and closes
    it. Only a failure of that attempt is "unreachable". No backend code and no far end
    can produce that outcome, and a backend with no endpoint is never "unreachable".
  - `ExecutingBackend.admit(request, bound)` then sends the admission request. It raises
    `PlacementUnavailable(code)`. It is called after both revalidations and before
    `commit`. `available()` keeps its meaning: a local precondition, no network.
- **C4 Every blocking call is bounded and interruptible.** `admit`, `commit`, `execute`,
  `cancel`, `kill`, `list_owned` and `release` take an `OperationBound(timeout_s,
  cancelled)`. A backend returns, or raises `sandbox_placement_operation_timeout`, within
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
    call with a remote effect.
  - A backend tags every sandbox it creates with the owner id and the lease id.
    `list_owned(owner_id, bound)` returns `(sandbox_ref, lease_id)` pairs;
    `kill(sandbox_ref, lease_id, bound)` is targeted.
  - The reaper decides by lease: it kills a listed sandbox only when that lease's lock is
    free. An owner that died between `commit` and recording its `sandbox_ref` is therefore
    still found, and a live leg of the same owner in that window is never killed.
  - The reaper runs at leg start and by command. A periodic reaper is not built: no backend
    planned so far bills by time. The cloud adapter adds one if it needs one.
- **C7 Where a seat may run: local is decided only before any admission request is sent.**
  This one rule carries two rulings (B3: at the cap wait, then not run, never local;
  unreachable before launch, run locally; and the credential floor) and removes any
  question of which comes first.

  | # | When | What happened | Outcome |
  |---|---|---|---|
  | 1 | Before anything is sent | The leg is not a placement candidate | **Local**, exactly as today |
  | 2 | Before anything is sent | The operator chose local for this run (`PHASE_LOOP_SANDBOX_PLACEMENT=local`) | **Local**, recorded `sandbox_placement_local_by_choice` |
  | 3 | Before anything is sent | The preflight fails. The preflight is supplied by the caller and uses only facts the launching host has; examples the follow-on plans add: the launching runtime is a source checkout and not a released build; the credential is not a kind that may be placed; the credential's remaining life, after one local renewal attempt where the runtime has one, is less than the floor **plus the admission-wait bound plus the transfer allowance**. | **Local**, with the preflight's typed code. No connection is attempted. |
  | 4 | Before any admission request | The driver's own connection attempt (C3) fails for **every** candidate | **Local**, recorded `seat_sandbox_root_fell_back` with each `<name>: sandbox_placement_unreachable` |
  | 5 | After an admission request was sent to any candidate | Admitted, committed, executed | **Placed** |
  | 6 | After an admission request was sent | The candidate answers `at_capacity`: retry with backoff until `PHASE_LOOP_SANDBOX_ADMIT_WAIT_S` is spent (default 600; `0` means no wait), then the next candidate; none admits | **Not run**, `sandbox_placement_capacity_exhausted` |
  | 7 | After an admission request was sent | Anything else before `execute`: not enrolled, the host is not the one pinned, a refusal by the far end for any reason, a capability unmet, a transfer failure, an operation timeout, a later candidate unreachable, **the caller's guard immediately before sealing fails** (for example a credential now under the floor) | **Not run**, with that outcome's typed code. A sandbox already created is released with confirmation first. |
  | 8 | After `execute` was called | Anything | The post-launch codes. Never started again, never moved. |

  - Rows 1 to 4, under the fail-closed knob, are refusals with zero spawns, as the knob
    means today.
  - A seat that reaches "local" through rows 3 or 4 has its local route decided from the
    local host's facts. **If that route is the sealed one the seat is not run**: a seat
    that was a placement candidate never runs sealed.
  - The decision is taken where `commit` is called today, after local staging and both
    revalidations. Nothing has been acquired for a placed launch at that point, so a seat
    that goes local continues from there exactly as today.
  - The preflight's sum is what makes row 7's guard a guard and not a path: a credential
    that passes the preflight still has its floor after the longest allowed wait and
    transfer. `PHASE_LOOP_SANDBOX_TRANSFER_ALLOWANCE_S` defaults to 300.
  - While a seat waits at the cap the monitor record carries `placement_wait`, the notice
    `seat_placement_waiting` is shown, and the stall clock does not run. A leg's stall
    clock starts when `execute` returns: admission, the wait and the transfer are not
    silence. For a bounded leg all three are charged to its deadline, as the login wait
    is.
  - **Codes.** The runtime owns a closed list of placement codes; a backend registers its
    own codes at registration, each mapped to one of the runtime's outcomes
    (`at_capacity`, `not_enrolled`, `identity_mismatch`, `refused`). The mapping is static
    and only chooses a wait and a fix line: under this rule no code a backend or a far end
    returns can lead to a local run. An unregistered code is recorded as
    `sandbox_placement_code_invalid`, never as backend text. A code that has a `NOTICES`
    row is added to the leg's seat notices.
- **C8 A candidate that is abandoned is released.** When the walk leaves a candidate after
  `admit` succeeded (a failed lease write, a failed `commit`, a failed guard, a cancel), it
  calls `release` on it, within a bound, before trying the next.
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
  reconnect follow-on plan amends `wait` and the driver's loop. It is held to these
  invariants, stated now so that nothing built here has to be undone:
  - the end of C2 is fixed at launch and no reconnect extends it; it applies while
    attached and while detached;
  - exactly one authority can end a kept workload, it is not something the workload can
    influence, and its failure to act is itself bounded by something else;
  - the far end can tell "the connection was lost" from "the owner ended or cancelled the
    workload": the driver always says the second explicitly, and silence means the first;
  - resume is bound to the lease id of C6 and to the principal that launched it; a detached
    leg is never started again and never moves;
  - a finished result survives a detach.
- **C13 A backend accounts for what it leaves behind.** A backend's plan states, for each
  process it runs on the far side, by name, what dies with it; and for a clean exit, a
  kill of each named process, an out-of-memory kill and a reboot, what state remains
  (processes, files, credentials in memory) and what removes it. "Nothing at rest" may be
  claimed only where it holds by construction; elsewhere the limit is stated. The tests
  name the process they kill.

## Consequences the maintainer should see

These follow from the rulings as recorded. None is hidden in a table.

- **A reachable compute host that refuses stops the seat; it does not send it home.** After
  an admission request has been sent, a refusal for any reason (a different build is
  installed there, the host failed its own checks, it is out of disk, this account's key
  is not enrolled) means the placed seats of that board are **not run** until someone
  fixes the host or the user chooses local for the run (`PHASE_LOOP_SANDBOX_PLACEMENT=local`,
  which every such refusal's fix line names). In the first design these ran locally.
- **Boards run from a source checkout** (the usual way boards run in this repository) are
  never the build a compute host has installed. The follow-on SSH plan must make "this
  runtime is not a released build" a preflight failure (row 3), so those boards run locally
  with a typed record instead of being refused.
- **A build that is merely newer or older than the compute host's** is learned only from
  the far end's answer, so it is row 7: not run, with a fix line naming both versions.
- **One limit for the whole account.** One seat's memory use can get another user's seat
  killed, and that seat is not run again.
- **"Runs locally" does not always mean the review happens.** A seat sent home by the
  credential preflight meets the local route's own credential rules there, which for some
  logins also refuse.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `PlacementRequest` — modify — optional deadline; `workload`, `required_capabilities`,
  `root`, `owner_id`, `lease_id`; `egress_needs` empty for a non-local candidate (C2, C5,
  C6, C10).
- `ExecSpec`, `ExecResult` — modify; `ExecProgress`, `OperationBound` — add (C1, C2, C4).
- `ExecutingBackend` — modify — `endpoint`, `admit`; the bound on each blocking call;
  `list_owned` and `kill` by lease (C3, C4, C6).
- `PLACEMENT_CODES`, `OUTCOMES` and `register_backend(scheme, backend, codes)` — add /
  modify — the runtime's closed code list, the four outcomes a backend code may map to,
  and registration of a backend's codes (C7). The four codes the seam already raises are
  entered here.
- `PlacementDecision` and `place(candidates, prepared, request_for, lease, *, preflight,
  guard, driver_enabled, bound)` — add — the C7 table, with C3's connection attempt, C8,
  and C10's refusal of a `leg` workload when `driver_enabled` is false. The flag is passed
  in, so `sandbox_placement` does not import the launch module. It returns one of: placed
  (a `LegPlacement`), local (with its row and code), not run (with its code).
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
- `candidate_roots(...)` — add — every configured non-local candidate whose scheme has a
  registered backend, in order; none when `PHASE_LOOP_SANDBOX_PLACEMENT=local`. No backend
  method is called and nothing is probed.
- `admit_wait_s()`, `transfer_allowance_s()` — add — the two settings, read with the
  `_env_int` idiom; defaults 600 and 300.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `seat_jail.py` (modify)
- `_HARNESS_DETAIL_CODES` and `NOTICES` — modify — every placement code in the list below
  becomes a member with a `(what, why, fix)` row. Nothing else in `panel_invoker.py`
  changes: the launch site and the flag are untouched.

  The codes: the two already listed; the four the seam already raises; and
  `sandbox_placement_lost_after_launch`, `sandbox_placement_lease_expired`,
  `sandbox_placement_end_reached`, `sandbox_placement_capability_unmet`,
  `sandbox_placement_capacity_exhausted`, `sandbox_placement_unreachable`,
  `sandbox_placement_not_enrolled`, `sandbox_placement_identity_mismatch`,
  `sandbox_placement_refused`, `sandbox_placement_workload_unsupported`,
  `sandbox_placement_operation_timeout`, `sandbox_placement_code_invalid`,
  `sandbox_placement_release_unconfirmed`, `sandbox_placement_local_by_choice`,
  `seat_placement_waiting`.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … A detail is one of: a HARNESS CODE — a
  fixed string this runtime itself emits (`_HARNESS_DETAIL_CODES`)". Members are added by
  that mechanism; no template or category is added.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `placement` command, action `reap` — add — runs `placement_lease.reap` for the configured
  backends. Its `dest`s are uniquely named.

### `phase-loop-runtime/tests/test_placement_driver.py`, `tests/test_placement_lease.py` (create); `tests/test_sandbox_placement.py`, `tests/test_seat_notices.py`, `tests/data/seat_launch_references.json`, `tests/test_agent_cli_scratch_inventory_1147.py` (modify)
- The falsifiers under "Verification".
- The inventories gain the rows the new modules and the `cli.py` edit add; the PR body lists
  them.
- `tests/test_sandbox_placement.py` keeps every flag-off test unchanged: the flag does not
  move. Its fake backend gains the new protocol members.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify —
  amendments C1–C13 in "Sandbox placement seam", the C7 table verbatim; the placement codes
  under "Leg `detail` vocabulary". The execution-gate and fail-closed paragraphs are **not**
  changed here: they describe the flag-off runtime, which is still what ships.
- `docs/phase-loop/convergence-runtime.md` — modify — the lease directory,
  `phase-loop placement reap`, and the three settings (they have no effect until a backend
  exists and the flag is on; the text says so).
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

**The C7 table, one row each, then its intersections.** Row 1 is decided by the caller
before the driver is entered; the launch site is not changed by this plan, so it has no
case here.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Row 2: local by choice | Local; zero connection attempts, zero backend calls | Probe before reading the setting |
| Row 3: the preflight fails | Local with the preflight's code; zero connection attempts, zero backend calls | Run the preflight after `admit` |
| Row 4: every candidate's endpoint is closed | Local; each reason recorded; zero `admit` calls | Let a backend report "unreachable" from `admit` |
| Row 4, one candidate closed and the next open | The open one is asked; from that point local is not possible | Decide from the first candidate only |
| Row 5 | Connection attempt, lease entry fsynced, `admit`, `commit`, guard, `execute`, `wait`, `release`, in that order; runtime `committed` and `completed` share one ref and the computed digest | Write the lease after `admit`; build `completed` from the backend's receipt |
| Row 6: at capacity, then admitted within the wait; wait spent with no other candidate | Placed; not run, `sandbox_placement_capacity_exhausted` | Fall back to local |
| Row 7, one case per outcome: not enrolled; identity mismatch; refused (one per registered code); capability unmet; `commit` raises; operation timeout | Not run with that code; a created sandbox is released and confirmed first; local is not possible | Treat any of them as unreachable |
| Row 7: the guard fails immediately before sealing | Released with confirmation; not run with the guard's code; `execute` was never called; **not local** | Go local on a guard failure |
| **Intersection (the one three reviewers found):** at capacity, then admitted, then the guard fails | Not run. Never local. | Let the credential rule override the capacity rule |
| Intersection: at capacity once, then the same candidate's endpoint is closed on retry; then a second candidate's endpoint is closed | Not run. Never local. | Decide locality from the last answer |
| Intersection: the preflight passes with exactly floor + wait + allowance, the wait runs to its end, then admitted | The guard passes; placed | Omit the wait from the preflight's sum |
| Rows 1 to 4 under the fail-closed knob | Refused, zero spawns | Let "local by choice" override the knob |
| Rows 3 and 4 where the local route is the sealed one | Not run | Run sealed |
| Row 8: failure after `execute` (raise, lost acknowledgement, `wait` raises, connection lost) | `sandbox_placement_lost_after_launch`; no second `execute` anywhere | Fall back on any exception |

**The rest of the contract.**

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| A backend's `admit` raises a code registered to any outcome, an unregistered code, prose, a path, 200 characters | Never local; the unregistered ones are `sandbox_placement_code_invalid` and their text appears in no record or log | Record `str(exc.reason)` |
| A backend with no endpoint | Never "unreachable": `admit` is called, and its failures are row 7 | Treat a missing endpoint as unreachable |
| Result that does not echo the request digest | No `completed` receipt; `sandbox_placement_lost_after_launch` | Skip the echo check |
| `admit` succeeded, then `commit` raises or the guard fails | `release` is called on that candidate before anything else | Skip the release |
| A backend whose `admit`, `commit`, `kill`, `list_owned` never return | Each ends within its bound as `sandbox_placement_operation_timeout`; a cancel during each returns within the bound | Wait without a timeout |
| Cancel during the capacity wait | Zero backend calls after it | Sleep through cancel |
| `must_end_within_s` reached while the fake keeps reporting progress; a renewal arrives just before | The driver cancels and the leg ends `sandbox_placement_end_reached`; the renewal did not move the end | Extend on renewal |
| `qualification` request while the flag is false | Driven; its receipts are marked and `applied_rule` is false for them | Count them as applied |
| `place` called with a `leg` workload while the flag is false | Refused by `place` itself: zero connection attempts, zero backend calls | Check the flag in the caller only |
| Backend lacking a required capability; declared but not verified after `commit` | `sandbox_placement_capability_unmet`; in the second case the sandbox is killed and confirmed first | Check `capabilities()` only |
| No-deadline leg on a backend with `max_lifetime_s`; deadline beyond it | Admitted and renewed while the lock is held; refused before `commit` | Refuse when `deadline_s is None` |
| Owner killed with SIGKILL between `commit` returning and the ref being recorded, while a second leg of the same owner is committing | `reap` kills the first leg's sandbox, found by its lease id, and leaves the second | Decide by `sandbox_ref` presence; liveness by pid |
| Another owner's sandbox; a paused sandbox on the second page | Survives; reaped | Drop the owner filter; first page only |
| `reap` with an empty lease directory, and with only live leases | Zero backend calls, no plugin import | Call `list_owned` unconditionally |
| Result received, then kill unconfirmed; no result, kill unconfirmed | Result kept with `sandbox_placement_release_unconfirmed`, entry remains; `sandbox_placement_lost_after_launch`, entry remains | Discard the result |
| A root written with userinfo and a query | `request.root` holds neither | Pass the configured text |
| Every placement code | A member of `_HARNESS_DETAIL_CODES` with a `NOTICES` row whose fix is non-empty; `_exception_failure` on each returns the code, not the unknown-failure template | Remove a row |
| Flag-off behaviour | Every existing test in `tests/test_sandbox_placement.py` passes unchanged in substance | Call a backend from `_default_spawn` |

## Acceptance criteria
- [ ] Each of rows 2 to 8 of the C7 table has a passing case (row 1 is decided by the
  caller before the driver is entered), and the two intersections hold: after an
  `at_capacity` answer followed by admission, a failing guard yields "not run" and never
  "local"; and a failing preflight yields "local" with zero connection attempts.
- [ ] "Unreachable" is produced only by the driver's own connection attempt to a closed
  endpoint: no code a backend raises, registered or not, results in a local run.
- [ ] With fake backends, `place` then `run_placed` yield runtime-attested `committed` and
  `completed` receipts for one `sandbox_ref` and the computed digest, with the lease entry
  fsynced before `admit`; an owner killed between `commit` and recording its ref has its
  sandbox reaped by lease id while a concurrent live leg of the same owner survives.
- [ ] A backend call that never returns ends within its bound, a cancel during it returns
  within the bound, and a workload still reporting progress at `must_end_within_s` is ended
  with `sandbox_placement_end_reached` whatever renewals arrived.
- [ ] `_NONLOCAL_EXECUTION_DRIVER` is still false, `place` itself refuses a `leg` workload
  while it is, and the existing flag-off tests in `tests/test_sandbox_placement.py` pass.

## Maintainer decisions

**Rulings of 2026-10-10** (relayed by the team lead; each was asked with options):

| Ruling | Where it lands |
|---|---|
| Route: a self-hosted compute host over SSH first; the cloud backend follows as overflow | The order of the follow-on plans |
| Busy or down (B3): at the cap, wait a bounded time, then not run, never local. Unreachable before launch: run locally with a loud typed record, until the cloud backend exists. A started seat never moves. | C7, rows 4, 6 and 8 |
| Credentials: expiring subscription tokens only; the renewal token never leaves the launching host; an API-key login or a stored long-lived seat token is refused for placement and the seat runs locally; no cap on a token's lifetime; a floor of 30 minutes of remaining life, in configuration, checked at the last moment before the credential is sealed into the request; refreshing a token inside a running seat is a named follow-on | C7, rows 3 and 7, give the rule its place: the preflight sends a seat home before anything is sent; the last-moment check is the guard, and its failure is "not run". The credential details are the placed-seat plans'. |
| Dropped connection (Q1): the far end keeps a started seat alive for a limited time and the launching host resumes it, tied to that run; the time is a setting with a default of about 30 minutes | C12's invariants; built by the reconnect follow-on plan |
| Signed attestation (Q3): deferred, not dropped; required before any gate relies on a far end's claims and before the cloud backend | The RD4 row of the supersession table |
| Accounts (B6): one shared account first, superseding RD1 (a) for the SSH work | The follow-on plans; RD3 legs (ii) is kept because of it |
| The built-in egress list is left as it is | C5 neither changes nor relies on it |
| Access (B5), default (B2), scope (B4) | The follow-on plans; RD3 stands |

**One rule in this plan is the team lead's reading of two of those rulings together, not a
ruling itself:** "local is decided only before any admission request is sent" (C7). It
honours "at the cap, never local" and "under the floor, run locally" by moving the floor
decision ahead of admission. Its cost is the first item under "Consequences".

**Open:** none.

Standing rulings this plan relies on, cited and not restated: R1 and R2
(agent-harness#1245); RD3, RD4, RD6 and CD1–CD4 (agent-harness#1162).

## Execution Policy

- execute: effort=high, reason=the contract every later plan and backend is held to; no launch-site change, but the admission and lease rules decide where a seat may run
