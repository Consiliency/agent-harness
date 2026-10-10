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
afterwards. This is the first slice. Every unit leaves main working: the driver flag stays
off until the unit after which a real backend can run a seat end to end.

| Unit | What | Flag | Where it is written |
|---|---|---|---|
| **P1** | **The driver ("plan 1b"): seam amendments, admission outcomes, lease journal, reaper, runtime receipts. Proven with fake backends.** | off | **This document** |
| P2 | An `ssh` backend, its compute-host entry point and `phase-loop placement qualify`, proven with a null workload | off | `plans/detailed-ssh-placement-backend-896-20261010.md` |
| P2b | A started workload survives a dropped connection and is resumed by the run that launched it | off | `plans/detailed-placement-reconnect-896-20261010.md` |
| P3 | The launch closure and the credential source factored so both hosts can call them. No behaviour change. | off | `plans/detailed-seat-launch-factoring-896-20261010.md` |
| P4 | The jailed Claude seat is placed: the execute branch, the leg request, the far end's seat run, sweep and separation probe. **The flag turns on here.** | on | `plans/detailed-remote-seat-execution-896-20261010.md` |
| P5 | Codex and grok seats run under a leased seat uid on the compute host, then are placed | on | `plans/detailed-placed-owned-seats-896-20261010.md` |

P1 and P3 do not depend on each other. P2 needs P1. P2b needs P2. P4 needs P2b and P3. P5
needs P4.

**What actually leaves the launching host.** On a four-seat board of Claude, codex, grok and
Gemini:

| After | Placed | Share of the board |
|---|---|---|
| P1, P2, P2b, P3 | nothing | 0 of 4 |
| P4 | the Claude seat | 1 of 4 |
| P5 | Claude, codex and grok, each only on a subscription login whose access token expires | 3 of 4 |

The Gemini seat is sealed on main (`seat_jail.GEMINI_RECORDED_STOP`), not jailed, so it is
never placed in this slice and stays on the launching host until agent-harness#1170. The
president and executors are out of scope (ruling B4).

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
| Task: "The cloud path is plan 1a, then 1b, then agent-harness#1165…" | **Superseded.** Order is 1a → this slice (self-hosted over SSH), then agent-harness#1165. | Maintainer, 2026-10-10 |
| Contract / "Request", "Execution types", "Receipts", "Execution gate" | **Amended** by C1–C12 below | Stated per amendment |
| Contract: every other subsection | Unchanged, still normative | |
| Follow-on / "Plan 1b" | **Superseded in full** by this document. Its rule "backends must tag every remote sandbox with the owner id and lease id at create" is **kept**, as C6. Its "periodic" reaper is **dropped**: see C6. | |
| Follow-on / "Plan 2" (egress allowlist from configuration) | **Unchanged and not scheduled.** The maintainer chose on 2026-10-10 to leave the built-in list as it is. This slice does not change it and does not rely on it: a placed seat's namespace is built with an empty private allowlist (C5). | Maintainer, 2026-10-10 |
| Follow-on / "Plan 3" (self-hosted HTTPS) | **Unchanged; sequenced after this slice.** | Maintainer, 2026-10-10 |
| Follow-on / "Plans 4a and 4b" | Unchanged; "1b" there now means P1 | |
| RD1 (a), one service and account per user | **Superseded for the first slice** by "one shared account first" (2026-10-10). Stands for the HTTPS service. | Maintainer, 2026-10-10 |
| RD3: seats only; legs (ii), codex and grok under a subordinate uid on the remote | **Both stand.** Legs (ii) is implemented by P5. Until P5, codex and grok are not placed. | |
| RD4 (a), "with a signed attestation" | (a) stands. **The signature is deferred, not dropped,** by the maintainer's ruling of 2026-10-10. It is a named follow-on, required before any gate relies on the far end's claims and before the cloud backend, where the far end is a third party. Until then the claims are unsigned and nothing reads them. | Maintainer, 2026-10-10 |
| RD5, a disk bound per sandbox | **(b) in this slice:** a measured bound that kills the seat over it (P4), plus a stage-size cap and a free-space floor (P2). (a), file-system quotas, is a host option the product does not require. | |
| R7 of the first draft, per-seat memory, CPU and task bounds | **Not in this slice, by ruling:** one limit bounds the whole account. Consequence, stated: one seat's memory use can get another user's seat killed, and that seat is not re-run. A named follow-on. | Maintainer, 2026-10-10 |
| RD6 | (a) stands for the legacy `host:path` form. (b) is exercised: an optional `ssh` backend (P2). | Maintainer, 2026-10-10 |
| RD2, CD1–CD4 | Unchanged. RD2 describes the HTTPS service; P2 states what SSH does instead. | |

**`plans/detailed-e2b-cloud-backend-896-20260929.md`**

| Section | Disposition |
|---|---|
| Task / "Chain" | **Amended:** 1a → P1 → 4a1 → 4a2 → 4b, sequenced after this slice |
| "Placement ordering", item 1, the deadline rule | **Amended** by C2 |
| "Asks of plan 1b": B2 (required capabilities) | **Delivered by P1** (C5) |
| "Asks of plan 1b": B4 (a control-plane qualification request) | **Delivered by P1** as the `qualification` workload (C10); first used by P2 |
| "Asks of plan 1b": B1, B3 | **Still owed.** They return to 4a1 as its own first changes. |
| "Asks of plan 2": A1 | **Met another way for placed seats:** C5 gives every placed seat an empty private allowlist. Plan 2 itself stays unscheduled. |
| "Follow-on: plan 4b", the in-VM layout | **Superseded; to be re-derived** from P4 and P5 when 4b is written |

**`plans/detailed-1244-seat-route-resolver-20261004.md`** (owned by the agent-harness#1244
lane; amended here because the 2026-10-10 rulings change it)

| Section | Disposition |
|---|---|
| "The chain", order of steps 1 and 2 | **Amended for a host with a remote root configured:** remote is tried first. The local sandbox is reached only when every remote candidate was unreachable (C7). |
| "The chain", step 3 (host-native fill) after a remote refusal | **Amended:** a seat refused for capacity, or by a reachable host for any reason, is not run. It is not filled natively on the launching host, which is as local as the local sandbox. |
| PR-A3: the `admit()` walk, typed remote codes, mode `remote` | **Delivered here** (C3, C7; the mode by P4), under the code names this plan gives. PR-A3 then moves the walk into the resolver, unchanged in substance. |

## Research summary

- **The gate.** `_NONLOCAL_EXECUTION_DRIVER = False` (`panel_invoker.py:4166`);
  `_placement_gate` (`:11669-11673`). P1 does not touch either.
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
  has a `seat_jail.NOTICES` row.
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
  commands are therefore named `phase-loop placement …`, not `sandbox …`.

## Contract amendments (normative for every unit of this slice and for agent-harness#1165)

P1 lands these in `advisor_board/CONTRACTS.md`, "Sandbox placement seam". Everything else
there stands: `prepare` is runtime code; `commit` follows both revalidations; launch is
final; backend receipts never make `sandbox_root_applied` true.

- **C1 The unit of execution is a workload the runtime owns, not an argv.** `ExecSpec` is
  `(workload, request, deadline_s, output_cap_bytes)`. `workload` is `leg` or
  `qualification`. A backend maps it to the runtime's own packaged worker and never
  receives an argv, a path or an environment built on the launching host. `request` is
  bytes and travels **only** on the backend's one-shot channel; a backend never writes it
  to a file system, an environment or a log. `ExecResult` is
  `(sandbox_ref, exit_status, result, truncated)`.
- **C2 A leg may have no deadline.** `PlacementRequest.deadline_s` and `ExecSpec.deadline_s`
  are `float | None`. With a deadline: a leg whose deadline exceeds
  `declaration().max_lifetime_s` is refused before `commit`, and renewal never passes it.
  Without one: the driver renews while, and only while, the owning process holds the lease
  lock; a backend's `max_lifetime_s` is then a liveness bound (ruling R2).
- **C3 Admission.** `ExecutingBackend.admit(request, bound)` may contact the backend and
  raises `PlacementUnavailable(code)`. It is called after both revalidations and before
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
    in this slice bills by time, and the SSH far end removes a sandbox whose session has
    ended. The cloud adapter adds one if it needs one.
- **C7 Admission outcomes are the runtime's, and only "unreachable" may run locally.** Each
  refusal code belongs to one class. The table is the runtime's own and static; a backend
  registers its codes with their class, the registration is checked against this table's
  classes, and nothing a backend says at run time changes a class. An unregistered code is
  `refused` and is recorded as `sandbox_placement_code_invalid`, never as backend text.

  | Class | Meaning | What the driver does |
  |---|---|---|
  | admitted | | `commit` |
  | `at_capacity` | The backend is reachable and full | Retry with backoff until `PHASE_LOOP_SANDBOX_ADMIT_WAIT_S` is spent (default 600; `0` means no wait), then the next non-local candidate. **From the first such answer on, this leg can no longer run locally**, whatever a later retry or candidate returns. |
  | `unreachable` | The runtime's own attempt to reach the backend failed below the backend's protocol | Next candidate |
  | `not_enrolled` | Reached; this account's credential was not accepted | Next non-local candidate. Never local. |
  | `identity_mismatch` | Reached; the host is not the one pinned | Next non-local candidate. Never local. |
  | `refused` | Reached; any other refusal: unqualified, below a floor, another version, a digest mismatch, a capability unmet, an unsupported workload, an operation timeout | Next non-local candidate. Never local. |

  With no candidate left:
  - every candidate ended `unreachable`, none answered `at_capacity`, and the fail-closed
    knob is off: a recorded local fallback (`seat_sandbox_root_fell_back`, with each
    `<name>: <code>` in `sandbox_root_reason`). The local route is then decided from the
    local host's facts, and **if that route is the sealed one the seat is not run**: a seat
    that was a placement candidate never runs sealed.
  - otherwise the seat is not run, with the code of the last decisive outcome
    (`sandbox_placement_capacity_exhausted`, `sandbox_placement_not_enrolled`,
    `sandbox_placement_identity_mismatch`, `sandbox_placement_refused`, or
    `sandbox_placement_required_unavailable` under the knob).

  A code that has a `NOTICES` row is added to the leg's seat notices, so the operator sees
  its fix line. While a seat waits at the cap the monitor record carries `placement_wait`,
  the notice `seat_placement_waiting` is shown, and the stall clock does not run. A leg's
  stall clock starts when `execute` returns: admission, the wait and the transfer are not
  silence. For a bounded leg all three are charged to its deadline, as the login wait is.
- **C8 A candidate that is abandoned is released.** When the walk leaves a candidate after
  `admit` succeeded (a failed lease write, a failed `commit`, a cancel), it calls `release`
  on it, within a bound, before trying the next.
- **C9 Runtime receipts.** The driver, which lives in `sandbox_placement` beside the seal,
  builds `committed` when `commit` returned for the digest the runtime computed, `launched`
  when it called `execute`, and `completed` when it received a terminal `ExecResult` for
  the same `sandbox_ref` whose result echoes the digest of the request the runtime sent.
  `sandbox_root_applied=true` for a placed leg therefore means: the runtime sent this leg to
  that backend and received its result on the same sandbox. It does not mean the runtime
  observed the seat's confinement; that is `sandbox_placement_verified`, and every entry
  there is a backend claim unless the runtime itself measured it.
- **C10 The gate governs legs; qualification is exempt.** `PlacementRequest.workload` is
  visible to the driver and to `admit`. Only the qualification entry point builds a
  `qualification` request: it transfers a synthetic tree, its records never count as an
  applied placement, and it may be driven while `_NONLOCAL_EXECUTION_DRIVER` is false. **The
  driver itself refuses a `leg` request while the flag is false**, before `admit`: the
  guard is in `place`, not left to its callers, so no future caller can place a seat by
  forgetting to check. A backend that cannot run a
  workload refuses it in `admit` (`sandbox_placement_workload_unsupported`, class
  `refused`), so nothing is transferred for a workload that will not run. The flag turns on
  in the unit after which a real backend runs a seat end to end (P4), not before.
- **C11 Confirmed release, and a finished review is kept.** `release` returns only when the
  sandbox is confirmed gone (`kill`, then absent from `list_owned`). If the result was
  already received and ingested, an unconfirmed kill does **not** discard it: the leg keeps
  its result, carries the notice `sandbox_placement_release_unconfirmed`, and the lease
  entry stays for the reaper. Without a result, an unconfirmed kill ends the leg with
  `sandbox_placement_lost_after_launch`.
- **C12 A lost connection to a started workload is a state, not an end** (ruling Q1 of
  2026-10-10). A backend that can keep a started sandbox alive without its controller says
  so in its declaration. For such a backend `ExecSpec` carries a reconnect window and an
  absolute time the sandbox must not be kept past: the earliest of the leg's deadline,
  where it has one, and the expiry of the credential placed with it, where one was placed.
  - When the backend loses its connection after `execute`, `wait` returns
    `ExecDetached(sandbox_ref, kept_until)` instead of raising. The driver keeps calling
    `wait`, which is the backend's chance to resume, until progress or a result arrives or
    `kept_until` passes; then the leg ends with `sandbox_placement_lost_after_launch`.
  - Launch stays final: a detached leg is never started again and never moves to another
    backend or to the launching host.
  - A bounded leg's deadline keeps running while detached. Under heartbeat-only the monitor
    record carries `placement_detached`, the stall clock does not run, and the notices
    `seat_placement_detached` and `seat_placement_resumed` are shown.
  - A cancel while detached is delivered at resume; the driver's cancel still returns
    within its bound (C4), leaving the lease entry for the reaper if the kill was not
    confirmed.
  - Resume belongs to the process that holds the lease's lock. A restarted runtime does not
    resume another process's leg; its reaper applies C6.
  - A backend that cannot keep a sandbox behaves as before: a lost connection after
    `execute` raises, and the leg ends.

## Changes (P1)

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `PlacementRequest` — modify — optional deadline; `workload`, `required_capabilities`,
  `root`, `owner_id`, `lease_id`; `egress_needs` empty for a non-local candidate (C2, C5,
  C6, C10).
- `ExecSpec`, `ExecResult`, `Declaration` — modify; `ExecProgress`, `ExecDetached`,
  `OperationBound` — add (C1, C4, C12).
- `ExecutingBackend` — modify — `admit`; the bound on each blocking call; `list_owned` and
  `kill` by lease (C3, C4, C6).
- `OUTCOME_CLASSES`, `PLACEMENT_CODES` and `register_backend(scheme, backend, codes)` —
  add / modify — the closed class table, the runtime's own codes, and registration of a
  backend's codes with their classes (C7). The four codes the seam already raises are
  entered here.
- `place(candidates, prepared, request_for, lease, bound) -> LegPlacement` — add — the C7
  walk with C8, and C10's refusal of a `leg` workload while the flag is false. The flag is
  read through an argument `panel_invoker` supplies, so `sandbox_placement` does not import
  the launch module.
- `run_placed(placement, spec, *, on_progress, cancelled) -> ExecResult` — add — `execute`,
  the `wait` loop, renewal, cancel and C11. After `execute` is called every exit is
  post-launch.
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
  registered backend, in order. No backend method is called and nothing is probed.
- `admit_wait_s()` — add — reads `PHASE_LOOP_SANDBOX_ADMIT_WAIT_S` with the `_env_int`
  idiom; default 600.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `seat_jail.py` (modify)
- `_HARNESS_DETAIL_CODES` and `NOTICES` — modify — every placement code in the list below
  becomes a member with a `(what, why, fix)` row. Nothing else in `panel_invoker.py`
  changes in this unit: the launch site and the flag are untouched.

  The codes: the two already listed; the four the seam already raises; and
  `sandbox_placement_lost_after_launch`, `sandbox_placement_lease_expired`,
  `sandbox_placement_capability_unmet`, `sandbox_placement_capacity_exhausted`,
  `sandbox_placement_unreachable`, `sandbox_placement_not_enrolled`,
  `sandbox_placement_identity_mismatch`, `sandbox_placement_refused`,
  `sandbox_placement_workload_unsupported`, `sandbox_placement_operation_timeout`,
  `sandbox_placement_code_invalid`, `sandbox_placement_release_unconfirmed`,
  `seat_placement_waiting`, `seat_placement_detached`, `seat_placement_resumed`.

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
  move in this unit. Its fake backend gains the new protocol members.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify —
  amendments C1–C12 in "Sandbox placement seam"; the placement codes under "Leg `detail`
  vocabulary". The execution-gate and fail-closed paragraphs are **not** changed here: they
  describe the flag-off runtime, which is still what ships.
- `docs/phase-loop/convergence-runtime.md` — modify — the lease directory and
  `phase-loop placement reap`.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md`, `docs/advisor-board-capabilities-card.md`
  — none: nothing an operator sees changes until P4.

## Dependencies & order
1. P1 needs plan 1a (merged) only.
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
call and record the order. `place` and `run_placed` are driven directly; `_default_spawn` is
not involved until P4. Each case is control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Admit, lease, commit, execute, wait, release | That order; the lease entry is on disk and fsynced before `admit`; runtime `committed` and `completed` share one ref and the computed digest | Write the lease after `admit`; build `completed` from the backend's receipt |
| Result that does not echo the request digest | No `completed` receipt; `sandbox_placement_lost_after_launch` | Skip the echo check |
| `at_capacity`, then admitted within the wait | Runs there | Stop at the first answer |
| `at_capacity`, wait spent, no other candidate, knob off | Not run, `sandbox_placement_capacity_exhausted`; `place` reports "local not allowed" | Fall back to local |
| `at_capacity` once, then the same candidate answers `unreachable`; and then a second candidate is `unreachable` | Not run; local not allowed | Decide from the last answer only |
| Every candidate `unreachable`, knob off / on | Local allowed with each reason recorded / `sandbox_placement_required_unavailable` | Drop the reasons |
| `not_enrolled`; `identity_mismatch`; `refused` (one case per registered code) | Next non-local candidate; with none, not run with that class's code; local not allowed | Treat any of them as `unreachable` |
| A backend registers a code with a class outside the table; a backend raises an unregistered code, prose, a path, 200 characters | Registration refused; `sandbox_placement_code_invalid`, and the text appears in no record or log | Record `str(exc.reason)` |
| A backend marks a capacity code "not retryable" at run time | Still `at_capacity` | Read the class from the exception |
| `admit` succeeded, `commit` raises | `release` is called on that candidate before the next is tried | Skip the release |
| A backend whose `admit` never returns; whose `commit`, `kill` and `list_owned` never return | Each ends within its bound as `sandbox_placement_operation_timeout`; a cancel during each returns within the bound | Wait without a timeout |
| Cancel during the capacity wait | Zero backend calls after it | Sleep through cancel |
| `qualification` request while the flag is false | Driven; its receipts are marked and `applied_rule` is false for them | Count them as applied |
| `place` called with a `leg` workload while the flag is false | Refused by `place` itself: zero backend calls | Check the flag in the caller only |
| Backend lacking a required capability; declared but not verified after `commit` | `sandbox_placement_capability_unmet`; in the second case the sandbox is killed and confirmed first | Check `capabilities()` only |
| Failure after `execute` (raise, lost acknowledgement, `wait` raises) | `sandbox_placement_lost_after_launch`; no second `execute` anywhere | Fall back on any exception |
| No-deadline leg on a backend with `max_lifetime_s`; deadline beyond it | Admitted and renewed while the lock is held; refused before `commit` | Refuse when `deadline_s is None` |
| Owner killed with SIGKILL between `commit` returning and the ref being recorded, while a second leg of the same owner is committing | `reap` kills the first leg's sandbox, found by its lease id, and leaves the second | Decide by `sandbox_ref` presence; liveness by pid |
| Another owner's sandbox; a paused sandbox on the second page | Survives; reaped | Drop the owner filter; first page only |
| `reap` with an empty lease directory, and with only live leases | Zero backend calls, no plugin import | Call `list_owned` unconditionally |
| A fake backend that keeps sandboxes: `wait` returns `ExecDetached`, then progress, then a result | One `completed` receipt; no second `execute`; `placement_detached` recorded; no stall notice while detached | Treat `ExecDetached` as a failure |
| The same, but `kept_until` passes with no resume; and a cancel arrives while detached | `sandbox_placement_lost_after_launch`, nothing run again anywhere; the cancel returns within its bound and is delivered first at resume | Start the leg again on the next candidate |
| A bounded leg detached past its deadline | Ends at the deadline; the window never extended it | Pause the deadline while detached |
| Result received, then kill unconfirmed; no result, kill unconfirmed | Result kept with `sandbox_placement_release_unconfirmed`, entry remains; `sandbox_placement_lost_after_launch`, entry remains | Discard the result |
| A root written with userinfo and a query | `request.root` holds neither | Pass the configured text |
| Every placement code | A member of `_HARNESS_DETAIL_CODES` with a `NOTICES` row whose fix is non-empty; `_exception_failure` on each returns the code, not the unknown-failure template | Remove a row |
| Flag-off behaviour | Every existing test in `tests/test_sandbox_placement.py` passes unchanged in substance | Call a backend from `_default_spawn` |

## Acceptance criteria
- [ ] With fake backends, `place` then `run_placed` yield runtime-attested `committed` and
  `completed` receipts for one `sandbox_ref` and the computed digest, with the lease entry
  fsynced before `admit`; a result that does not echo the request digest yields no
  `completed` receipt.
- [ ] A candidate that answered `at_capacity` once makes the leg ineligible for local
  fallback even when every later answer is `unreachable`; only an attempt in which every
  candidate was `unreachable` reports "local allowed".
- [ ] A backend call that never returns ends within its bound as
  `sandbox_placement_operation_timeout`, and a cancel during it returns within the bound.
- [ ] An owner killed between `commit` and recording its `sandbox_ref` has its sandbox
  reaped by lease id while a concurrent live leg of the same owner survives.
- [ ] `_NONLOCAL_EXECUTION_DRIVER` is still false, and the existing flag-off tests in
  `tests/test_sandbox_placement.py` pass.

## Maintainer decisions

**Rulings of 2026-10-10** (relayed by the team lead; each was asked with options):

| Ruling | What it fixes in this plan |
|---|---|
| Route: a self-hosted compute host over SSH first; the cloud backend follows as overflow | The slice |
| Busy or down (B3): at the cap, wait a bounded time, then not run, never local. Unreachable before launch: run locally with a loud typed record, until the cloud backend exists. A started seat never moves. | C7 |
| Accounts (B6): one shared account first, superseding RD1 (a) for the first slice | P2, P4, P5; RD3 legs (ii) is kept because of it |
| The built-in egress list is left as it is | C5 neither changes nor relies on it |
| Scope (B4): seats only | RD3 stands |
| Dropped connection (Q1): the compute host keeps a started seat alive for a limited time and the launching host resumes it, tied to that run; the time is a setting with a default of about 30 minutes | C12 here; built by P2b |
| Signed attestation (Q3): deferred, not dropped; required before any gate relies on the far end's claims and before the cloud backend | The RD4 row of the supersession table; a named follow-on |
| Credentials: expiring subscription tokens only. A placed seat gets only the access token of the launching user's subscription login; the renewal token never leaves the launching host; an API-key login or a stored long-lived seat token is refused for placement and the seat runs locally. No cap on a token's lifetime. A floor of 30 minutes of remaining life, in configuration, checked at the last moment before the credential is sealed into the request. Refreshing a token inside a running seat is a named follow-on. | P4, P5 |

**Open:** none.

Standing rulings this plan relies on, cited and not restated: R1 and R2
(agent-harness#1245); RD3, RD4, RD6 and CD1–CD4 (agent-harness#1162).

## Execution Policy

- execute: effort=high, reason=the contract every later unit and backend is held to; no launch-site change, but the admission and lease rules decide where a seat may run
