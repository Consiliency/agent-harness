---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1246, agent-harness#1162, agent-harness#1165, agent-harness#1245, agent-harness#1222, agent-harness#1166, agent-harness#1253]
amends: [plans/detailed-remote-sandbox-placement-896-20260929.md, plans/detailed-e2b-cloud-backend-896-20260929.md]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py tests/test_sandbox_policy.py tests/test_sandbox_egress.py tests/test_sandbox_retention.py tests/test_seat_notices.py tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py tests/test_panel_leg_status_detail_1096.py tests/test_review_monitor_policy.py tests/test_harden_evidence_producer.py tests/test_harden_evidence_verifier.py tests/test_launchspec_golden.py tests/test_agent_cli_scratch_inventory_1147.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: the execution driver for non-local placement — admission, lease journal, heartbeat, reaper, execute branch (agent-harness#896, plan 1b, brought up to date)

## Task

A shared host that launches a review board runs every seat itself, because only the
placement seam exists (agent-harness#1246). The maintainer ruled on 2026-10-10 that seats
move to a self-hosted compute host **over SSH first**, with the cloud backend as overflow
afterwards. This is the first slice, in three units that each fit one review board:

| Unit | What | Where it is written |
|---|---|---|
| **P1** | **The runtime's execution driver ("plan 1b"): admission, lease journal, heartbeat, reaper, the execute branch. Vendor-neutral; proven with a fake backend.** | **This document** |
| P2 | An `ssh` executing backend and the entry point it talks to on the compute host, proven with a null workload | `plans/detailed-ssh-placement-backend-896-20261010.md` |
| P3 | A seat runs through that entry point: the same launch path, per-run credentials, the `remote` seat mode | `plans/detailed-remote-seat-execution-896-20261010.md` |

After P3, plus the one-time setup of the compute host and its tailnet grant (owned outside
this repository), a board's seats are staged and revalidated on the launching host,
transferred, executed in the seat sandbox on the compute host, and returned under
runtime-attested receipts.

P1 changes no behaviour for a host with no remote root configured. No real backend exists
until P2. **No maintainer decision is open for P1.**

**Cited follow-ons, unchanged by this slice:** the cloud adapter (agent-harness#1165, plans
4a1, 4a2, 4b) and the self-hosted HTTPS service ("Plan 3" of the placement plan, with the
maintainer's 2026-10-04 requirements on agent-harness#896). Both sit behind the same driver.

**No roadmap goal IDs apply.** The v11 roadmap proposal (agent-harness#1394) does not
schedule this work, so this plan references agent-harness#896's and agent-harness#1244's
acceptance items and restates none.

## What this plan supersedes and amends

Sections not listed are unchanged. Plan 1a's own Changes, Verification and Acceptance are
history: agent-harness#1246 implemented them. The change that adds this plan also adds one
line under each amended plan's title pointing at this table, and changes nothing else in
them.

**`plans/detailed-remote-sandbox-placement-896-20260929.md`**

| Section | Disposition | Why |
|---|---|---|
| Task: "The cloud path is plan 1a, then 1b, then agent-harness#1165. It no longer passes through the self-hosted plan." | **Superseded.** Order is 1a → P1 → P2 → P3 (self-hosted over SSH), then agent-harness#1165. | Maintainer, 2026-10-10 |
| Contract / "Request" (`deadline_s`) | **Amended** by amendment C2 | Heartbeat-only legs have no deadline |
| Contract / "Execution types" | **Superseded** by amendment C1 | A seat launch is no longer an argv (agent-harness#1222) |
| Contract / "Receipts" | **Amended** by amendment C4 (who builds `committed` and `completed`) | Nothing on main builds them |
| Contract: every other subsection | Unchanged, still normative | |
| Follow-on / "Plan 1b" | **Superseded in full** by this document | Three partial sources, now one |
| Follow-on / "Plan 2" (egress allowlist from configuration) | **Unchanged and not scheduled.** The maintainer chose on 2026-10-10 to leave the built-in list as it is for now. This slice does not change it and does not rely on it. | Maintainer, 2026-10-10 |
| Follow-on / "Plan 3" (self-hosted HTTPS) | **Unchanged; sequenced after this slice.** The SSH backend is a different, optional backend, not a replacement. | Maintainer, 2026-10-10 |
| Follow-on / "Plans 4a and 4b" | Unchanged; "1b" there now means P1 | |
| Maintainer decisions: RD6 | **(a) stands** for the legacy `host:path` form, which stays record-only. **(b) is exercised:** an optional SSH backend, as the URL scheme `ssh`, specified in P2. | Maintainer, 2026-10-10 |
| Maintainer decisions: RD1–RD5, CD1–CD4 | Unchanged. RD1, RD2 and RD5 describe the HTTPS service; what the SSH backend does instead is stated in P2. | |

**`plans/detailed-e2b-cloud-backend-896-20260929.md`**

| Section | Disposition | Why |
|---|---|---|
| Task / "Chain" | **Amended:** 1a → {P1, plan 2} → 4a1 → 4a2 → 4b, sequenced after P3 | Maintainer, 2026-10-10 |
| "Placement ordering", item 1, "the leg deadline exceeds `max_lifetime_s`" | **Amended** by C2 | No-deadline legs |
| "Asks of plan 1b": B2 | **Delivered by P1** (amendment C5) | |
| "Asks of plan 1b": B4 | **Delivered by P2**, as the null workload run through the same driver | No parallel path |
| "Asks of plan 1b": B1, B3 | **Still owed; not delivered by this slice.** They return to 4a1 as its own first changes. | They exist for the cloud key and the per-repository opt-out only |
| "Asks of plan 2": A1 | **Still owed.** Plan 2 is not scheduled (above). | |
| "Follow-on: plan 4b", the in-VM layout and "Codex and grok stay refused" | **Superseded; to be re-derived** from SEATOWNER and P3's leg execution when 4b is written. Not rewritten here. | Predates agent-harness#1222 and agent-harness#1253 |
| 4a1 design, 4a2 | Unchanged | |

**Cross-plan note, not an amendment.** `plans/detailed-1244-seat-route-resolver-20261004.md`
belongs to the agent-harness#1244 lane. P1 delivers three of its PR-A3 prerequisites
(admission, sandbox timestamps, no-deadline lifetime). Its chain lists the local sandbox
before the remote one, while root selection on main tries a configured remote root first;
this slice keeps main's order, because a configured root is the operator's statement of
where seats should run. The agent-harness#1244 chain is otherwise untouched: a seat that
cannot be placed falls to the next backend, then to local or to not-run, and is never run
sealed.

## Research summary

- **The launch site.** `panel_invoker._default_spawn` selects a root
  (`sandbox_policy.select_sandbox_root`, with `_placement_gate` as `accept`), runs
  `prepare_local_stage`, both revalidations, then `backend.commit`, then the fail-closed
  backstop `_refuse_unless_executed_remotely(mode, executed_remotely=False)`, then acquires the
  local egress namespace, then takes a launch branch. In the brokered branch the provider is
  launched from the `_parent_infer` closure by `_exec_jailed_claude_leg`,
  `_exec_claude_tui_leg` or `_exec_leg`; the provider is a child of the runtime, never of the
  broker's probe client. The `finally` closes egress, calls `backend.release` and resets the
  leg's facts.
- **The gate.** `_NONLOCAL_EXECUTION_DRIVER = False` (`panel_invoker.py:4166`);
  `_placement_gate` (`:11669-11673`).
- **Gaps in the seam as built** (`sandbox_placement.py`):
  - `ExecSpec.deadline_s` and `PlacementRequest.deadline_s` are non-optional floats, and
    `_placement_request` sends a finite deadline even under `heartbeat_only`;
  - `ExecutingBackend` has no admission call and no progress signal;
  - `ExecSpec` carries one secret; SEATOWNER gives codex, grok and gemini credential *files*
    in a private home and Claude a token on a descriptor;
  - a runtime-attested `committed` or `completed` receipt is built nowhere, although
    `applied_rule` and `verify_harden_evidence.verify_sandbox_placement` both require them;
  - no test names `ExecSpec` or `ExecResult`, and no backend exists, so amending them breaks
    no consumer.
- **Monitoring.** Under `heartbeat_only` a leg has no deadline and ends only by completion or
  cancel; `_ReviewMonitor` records progress age and raises a notice, never a kill. Bounded
  legs keep a stall kill and a wall clock.
- **Reusable patterns.** A lock per lease with no pid: `seat_uid.lease_seat_id`. A
  non-blocking lock probe: `convergence/broker/admission.py`. An fsynced append with
  directory fsync: `convergence/event_log._append`. Atomic publish:
  `sandbox_retention._publish_atomically`. Per-user state: `seat_jail.state_home()`.
  `lease_store.py` and `dispatch_lock.py` are repository-local and decide liveness by
  timestamp or pid; they are not reused.
- **Vocabulary.** A leg `detail` is a member of `_HARNESS_DETAIL_CODES`; a notice with a fix
  line is a `(what, why, fix)` row in `seat_jail.NOTICES`. The two existing
  `sandbox_placement_*` codes have no `NOTICES` row.
- **The reaper hook.** `_gc_stale_panel_scratch` is called once, inside the per-leg spawn.

## Contract amendments (normative for P1, P2, P3 and agent-harness#1165)

P1 lands these in `advisor_board/CONTRACTS.md`, "Sandbox placement seam". Everything else in
that section stands, including: `prepare` is runtime code; `commit` follows both
revalidations; launch is final; backend receipts never make `sandbox_root_applied` true.

- **C1 The unit of execution is a leg, not an argv.** `ExecSpec` is
  `(kind, request, deadline_s, output_cap_bytes)`.
  - `kind` is `leg` or `null`. A backend maps it to the runtime's own packaged worker; it
    never receives an argv, a path or an environment built on the launching host.
  - `request` is bytes: the sealed leg request. It travels **only** on the backend's
    one-shot channel. A backend never writes it to disk, an environment or a log.
  - `ExecResult` is `(sandbox_ref, exit_status, result, truncated)`; `result` is the sealed
    leg result. It is a claim until the runtime has ingested it (C6).
- **C2 A leg may have no deadline.** `PlacementRequest.deadline_s` and `ExecSpec.deadline_s`
  are `float | None`.
  - With a deadline: a leg whose deadline exceeds `declaration().max_lifetime_s` is refused
    before `commit`, and renewal never passes the deadline.
  - Without one: the driver renews the sandbox while, and only while, the owning process
    holds the lease lock. A backend's `max_lifetime_s` is then a liveness bound (ruling R2):
    a leg that reaches it ends with `sandbox_placement_lease_expired`, after launch, with no
    fallback.
- **C3 Admission and progress.**
  - `ExecutingBackend.admit(request) -> None` may contact the backend. It raises
    `PlacementUnavailable(code)`. It is called only when the driver flag is true, after both
    revalidations and before `commit`. A refusal is pre-launch.
  - A refusal may be marked `retryable` (for example: the backend is at its concurrency
    cap). The driver then retries `admit` on that candidate, with backoff, until
    `PHASE_LOOP_SANDBOX_ADMIT_WAIT_S` has elapsed (default 0: no wait), and only then treats
    it as a refusal. The wait is before launch, is ended by cancel, and for a bounded leg is
    charged to its deadline.
  - `wait(sandbox_ref, wait_s)` returns an `ExecResult` or an `ExecProgress(sandbox_ref,
    seq)`. A rising `seq` is a liveness signal for the review monitor and nothing else. It
    is a backend claim and never evidence.
- **C4 Runtime receipts.** The driver, which lives in `sandbox_placement` beside the seal,
  builds `committed` when `commit` returned for the digest the runtime computed, `launched`
  when it called `execute`, and `completed` when it received a terminal `ExecResult` for
  the same `sandbox_ref`.
- **C5 Required capabilities** (ask B2). `PlacementRequest.required_capabilities` for a
  review leg: `inbound_closed`; `one_shot_secret_channel`; and `private_ranges_unreachable`,
  or `private_allowlist` when `egress_needs` is not empty. `egress_needs` keeps its
  present source; a backend applies its own host's policy and a request never widens it. The driver refuses before `admit`
  if the set is not within `capabilities()`, and again after `commit`, before `execute`, if it
  is not within `verified`; the second refusal kills the sandbox with confirmation first.
  Both are `sandbox_placement_capability_unmet`.
- **C6 Outcome authority stays local.** The runtime ingests `result` under a size cap and a
  strict decode, redacts the leg's registered credential values and runs the secret scan,
  and only then builds the leg record with the same classification code a local leg uses. A
  `detail` in the result is kept only if it is a member of `_HARNESS_DETAIL_CODES`; a notice
  only if it is a `NOTICES` code. Anything else in the result is stored as a claim that no
  gate, verifier or closeout reads.
  - **The broker record of a placed leg holds only what the runtime observed.** It carries
    `provider_placement: <backend name>`, the harness and model, and the digest and size of
    the prompt, of the request it sent and of the result it ingested. The eight keys that
    describe a provider process the runtime launched here are **absent**, not filled from
    the backend: `provider_argv_shape`, `provider_argv_sha256`, `provider_cwd_class`,
    `provider_cwd_sha256`, `provider_env_keys`, `provider_env_api_keys_scrubbed`,
    `provider_env_direct_routes_scrubbed`, `provider_no_tool_controls`. The verifier
    enumerates this second shape; it is never accepted by prefix. A placed leg is a tooled
    seat, so EC-HARDEN-5 is reported UNMET for it exactly as for a local tooled seat.
- **C7 Order and fallback.** Candidates are the configured roots in order. For each: the C5
  check, `admit`, the lease entry, `commit`. A `PlacementUnavailable` at any of these moves to
  the next candidate and adds `<name>: <code>` to `sandbox_root_reason`; only the validated
  code is recorded, never backend prose. A code that has a `NOTICES` row is also added to
  the leg's seat notices, so the operator sees its fix line. With none left: a recorded local fallback, or
  `sandbox_placement_required_unavailable` under the fail-closed knob. A refused seat is
  never run sealed.
- **C9 A backend is told its root.** The seam as built gives a backend no way to learn the
  root that selected it. `PlacementRequest.root` carries the parsed, sanitized location
  (scheme, host with optional port, path) and the configured backend name. It is the form
  `sandbox_policy.parse_location` already produces, so userinfo, query and fragment never
  reach a backend.
- **C8 Confirmed release.** `release` on a non-local placement returns only when the
  sandbox is confirmed gone (`kill`, then absent from `list_owned`). An unconfirmed kill
  ends the leg with `sandbox_placement_lost_after_launch` and leaves the lease entry for
  the reaper.

## Changes (P1)

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_placement.py` (modify)
- `PlacementRequest` — modify — `deadline_s: float | None`; add `required_capabilities` and
  `root` (C2, C5, C9).
- `PlacementUnavailable` — modify — add `retryable: bool = False` (C3). `str()` stays the
  bare code.
- `ExecSpec`, `ExecResult` — modify; `ExecProgress` — add (C1, C3).
- `ExecutingBackend.admit` — add; `ExecutingBackend.wait` — modify (C3).
- `LegPlacement.record_runtime(step)` — add — the only builder of runtime `committed`,
  `launched` and `completed` receipts for a non-local placement (C4).
- `place(candidates, prepared, request, lease) -> LegPlacement` — add — the C7 walk.
- `run_placed(placement, spec, *, on_progress, cancelled) -> ExecResult` — add — `execute`,
  the `wait` loop, renewal, cancel, and C8. After `execute` is called, every exit is
  post-launch: it never returns control to a local launch.
- `register_backend` — modify — the protocol check now includes `admit`.

### `phase-loop-runtime/src/phase_loop_runtime/placement_lease.py` (create)
- `owner_id()` — add — a per-user random id under `state_home()/phase-loop/` (0600).
- `open_lease(backend_name) -> Lease` — add — one file per lease under
  `state_home()/phase-loop/placement-leases/` (directory 0700, file 0600), written and
  fsynced with its directory **before `commit`**, and held under `flock` by the owning
  process for the life of the leg. It records the backend name, the `sandbox_ref` once
  known, `created_at` and `confirmed_killed_at`. It never records request or result bytes.
- `Lease.heartbeat(backend, sandbox_ref, deadline_s)` — add — a thread that calls
  `backend.renew` on an interval and stops with the leg (C2).
- `reap(backends)` — add — driven by the journal: a backend is contacted only when a lease
  entry naming it exists and that entry's lock is free (a non-blocking probe). With no such
  entry `reap` makes no backend call. For a contacted backend: `list_owned(owner_id())`
  across every page and state; kill only a sandbox whose lease lock is free; confirm; then
  clear the entry. Liveness is never decided by pid or age.

### `phase-loop-runtime/src/phase_loop_runtime/placement_leg.py` (create)
- `encode_request(...)` / `decode_request(...)` — add — the sealed leg request, schema
  `placement_leg_request.v1`: harness, model, effort, mode, monitoring policy, the staged
  bundle and instructions with their digests, the snapshot digest, and a credential slot
  that P1 always leaves empty (P3 fills it).
- `encode_result(...)` / `ingest_result(...)` — add — schema `placement_leg_result.v1`, and
  the C6 ingestion.

### `phase-loop-runtime/src/phase_loop_runtime/sandbox_policy.py` (modify)
- `candidate_roots(...)` — add — every configured non-local candidate whose scheme has a
  registered backend, in order, plus the local fallback choice. No backend method is
  called, and nothing is probed, as today.
- `admit_wait_s()` — add — reads `PHASE_LOOP_SANDBOX_ADMIT_WAIT_S` with the existing
  `_env_int` idiom; default 0.
- `select_sandbox_root` — unchanged for local and `hostpath` roots.

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_NONLOCAL_EXECUTION_DRIVER` — modify — `True`, in this same change.
- `_default_spawn` — modify:
  - after both revalidations, `sandbox_placement.place(...)` replaces the single `commit`
    call for a leg with non-local candidates. A leg the runtime defers to the driving
    session is never placed.
  - `_refuse_unless_executed_remotely` receives `executed_remotely=True` exactly when the
    leg is committed to a non-local backend.
  - For such a leg the local egress namespace and the seat-uid lease are not acquired: no
    provider runs here. The local enforcement facts are recorded as not applied, with a
    reason naming the placement. The implementer first confirms that no consumer of
    `sandbox_network_filtered` turns that into a refusal; one that does takes the same
    execution-based exemption as the knob.
  - `_exec_placed_leg` — add — one helper, called from `_parent_infer` and from the
    unbrokered branch in place of the three local exec functions. It builds the request,
    calls `run_placed`, feeds `ExecProgress` to the review monitor, maps the broker latch's
    cancel to `backend.cancel`, and returns the same shape those functions return.
  - Bounded legs keep the stall and wall-clock rules, applied to `ExecProgress`.
  - The `finally` releases through C8.
- `_placement_request` — modify — `deadline_s=None` when a review monitor is present;
  `required_capabilities` per C5; `root` from the candidate being tried (C9).
- The `_gc_stale_panel_scratch` call site — modify — also runs `placement_lease.reap`, best
  effort. It reads the lease directory first: with no stale entry it imports no plugin and
  makes no call, so an ordinary leg start costs one directory listing.
- `_HARNESS_DETAIL_CODES` — modify — add exactly `sandbox_placement_lost_after_launch`,
  `sandbox_placement_lease_expired`, `sandbox_placement_capability_unmet`,
  `sandbox_placement_result_invalid`.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … A detail is one of: a HARNESS CODE — a
  fixed string this runtime itself emits (`_HARNESS_DETAIL_CODES`)". This adds four members
  by that mechanism, and no template or category.
- `_record_sandbox_facts` / `_sandbox_evidence` — modify — add
  `sandbox_placement_created_at` and `sandbox_placement_confirmed_killed_at` when the
  placement is non-local.
- The broker's provider evidence — modify — for a placed leg it is the C6 shape: no
  local-launch key is written.

### `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py` (modify)
- `NOTICES` — modify — one `(what, why, fix)` row for each of the six `sandbox_placement_*`
  detail codes, the two existing ones included. Every placement refusal then has a fix line.

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `sandbox` command, action `reap` — add — runs `placement_lease.reap` for the configured
  backends. It uses its own uniquely named `dest`s, as `seat-sandbox` does.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)
- `SANDBOX_OPTIONAL_KEYS` — modify — add the two timestamp keys, enumerated, with a format
  check. The placement rule is unchanged.
- `verify_broker` — modify — the placed-leg shape of C6: when `provider_placement` is
  present, the local-launch keys must be absent, `sandbox_placement_backend` must equal it
  and `sandbox_local_provider_spawns` must be 0; when it is absent, today's key set is
  required unchanged. `harden5_unmet` is true for a placed record. The eight absent keys
  are the ones `_record_broker_provider_evidence` writes about the local launch
  (`panel_invoker.py:6375-6419`).

### `phase-loop-runtime/tests/test_placement_driver.py`, `tests/test_placement_lease.py` (create); `tests/test_sandbox_placement.py`, `tests/test_harden_evidence_verifier.py`, `tests/test_seat_notices.py` (modify)
- The falsifiers under "Verification".
- `test_sandbox_placement.py`'s execution-gate test asserts zero backend calls while the
  flag is false. It is **replaced**, not deleted: the PR body lists it and the test that
  takes its place.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify —
  amendments C1–C8 in "Sandbox placement seam"; the execution-gate paragraph now says the
  driver exists; the four codes under "Leg `detail` vocabulary".
- `docs/phase-loop/convergence-runtime.md` — modify — replace "This release has no driver
  that executes on a non-local backend"; document the lease directory, `phase-loop sandbox
  reap`, and what the fail-closed knob now exempts.
- `docs/advisor-board-capabilities-card.md` — modify — where a placed seat's duration is
  recorded (ruling R2).
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none: no operator-visible change
  until a backend exists.

## Dependencies & order
1. P1 needs plan 1a (merged) only.
2. P1 lands after the 0.7.27 seat fixes. It edits `panel_invoker.py` and `seat_jail.NOTICES`,
   which those fixes also edit; it merges main before its board and does not start from an
   older base.
3. agent-harness#1244's PR-A1 moves route selection into a resolver. Whichever of PR-A1 and
   P1 lands second moves the C7 walk to where selection then lives; the walk itself does
   not change.
4. No agy route-core file is edited. The next release cut requalifies agy as usual.
5. Order within P1: the tests first, failing on the missing symbols (the RED receipt);
   `sandbox_placement`; `placement_lease`; `placement_leg`; `sandbox_policy`;
   `panel_invoker` with the flag; the verifier; the CLI.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_placement_driver.py tests/test_placement_lease.py tests/test_sandbox_placement.py \
  tests/test_sandbox_policy.py tests/test_sandbox_egress.py tests/test_sandbox_retention.py \
  tests/test_seat_notices.py tests/test_seat_owner_notices.py \
  tests/test_seat_reference_inventory.py tests/test_panel_leg_status_detail_1096.py \
  tests/test_review_monitor_policy.py tests/test_harden_evidence_producer.py \
  tests/test_harden_evidence_verifier.py tests/test_launchspec_golden.py \
  tests/test_agent_cli_scratch_inventory_1147.py
ruff check .
```

Run on Python 3.12 and 3.10. The backend is a conformant in-process fake that counts every
method call and records the order. Each case is control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Execute path, through `_default_spawn` | `prepare`, both revalidations, `admit`, lease entry, `commit`, `execute`, `wait`, `release`, in that order; zero local provider spawns; runtime `committed` and `completed` share one ref and the authorization digest; `sandbox_root_applied=true`; the verifier accepts the record | Build `completed` from the backend's receipt |
| Revalidation fails | Zero backend calls; no lease entry | Call `admit` before revalidation |
| No remote root configured | The local-equivalence golden of plan 1a still matches; no plugin import; no lease directory created | Create the lease directory at import |
| First candidate refuses in `admit`, second admits | Runs on the second; `sandbox_root_reason` names the first and its code | Stop at the first refusal |
| Candidate refuses `retryable`, then admits within the wait; and never admits | Runs there after the retry; with the wait exhausted it is a refusal like any other; with the wait at 0 `admit` is called once; cancel during the wait ends the leg with zero backend calls after it | Sleep through cancel; retry a non-retryable code |
| Every candidate refuses, knob off | Local run; `sandbox_root_fell_back=true`; each `<name>: <code>` recorded | Drop the reasons |
| Every candidate refuses, knob on | `sandbox_placement_required_unavailable`; zero spawns; the leg is not run sealed | Fall back to local |
| Refusal code is not a code (prose, a path, 200 characters) | Recorded as a fixed invalid-code marker; the text appears nowhere in the record or log | Record `str(exc.reason)` |
| Failure after `execute` (raise, lost acknowledgement, `wait` raises) | `sandbox_placement_lost_after_launch`; zero local spawns; no second `execute` on any backend | Fall back on any exception |
| No-deadline leg, backend with a `max_lifetime_s` | Admitted; renewed while the lease lock is held; never refused for the lifetime | Refuse when `deadline_s is None` |
| Deadline beyond `max_lifetime_s` | Refused before `commit`; next candidate | Refuse after `commit` |
| Renewal | Stops when the leg ends; with a deadline, never passes it | A thread that outlives the leg |
| Lease entry | On disk and fsynced before `commit` is called | Write after `commit` |
| Owner killed with SIGKILL after `commit` | The next `reap` kills its sandbox and clears the entry | — |
| Live lease held by a second process of the same owner; another owner's sandbox | Both survive `reap` | Liveness by pid; drop the owner filter |
| A paused sandbox on the second page of `list_owned` | Reaped | First page only; running only |
| Kill cannot be confirmed | `sandbox_placement_lost_after_launch`; the entry remains | Clear the entry on `kill` returning |
| Required capability not declared; declared but not verified after `commit` | `sandbox_placement_capability_unmet`; in the second case the sandbox is killed and confirmed before the next candidate | Check `capabilities()` only |
| Result over the cap; truncated; undecodable; a `detail` outside the vocabulary; a credential value in the text | `sandbox_placement_result_invalid`, or the unknown-detail template, or the value redacted; never raw bytes in a record | Trust the result's `detail` |
| Cancel through the broker latch | `backend.cancel` called; the leg returns only after confirmed kill | Return before confirmation |
| Bounded leg with no progress for the stall window | Cancelled with the same stall detail a local leg gets | Count `wait` returning as progress |
| Each of the six placement codes | A member of `_HARNESS_DETAIL_CODES` with a `NOTICES` row that has a non-empty fix | Remove a row |
| A root written with userinfo and a query | The backend's `request.root` holds neither | Pass the configured text |
| The request | Its bytes appear in no lease file, evidence record, leg log or exception text | Log the spec |
| Broker record of a placed leg | Passes the verifier's placed shape and is reported EC-HARDEN-5 UNMET; the same record with one local-launch key added, or a local record with `provider_placement` added, is rejected | Fill a local-launch key from the backend |
| `reap` with an empty lease directory, and with only live leases | Zero backend calls | Call `list_owned` unconditionally |

## Acceptance criteria
- [ ] With a conformant fake backend registered for a configured root, a review leg run
  through `_default_spawn` records zero local provider spawns and
  `sandbox_root_applied=true`, and `verify_harden_evidence.py` accepts the record; with
  `completed` taken from the backend it is rejected.
- [ ] A failure injected after `execute` ends the leg with
  `sandbox_placement_lost_after_launch`, zero local spawns and no second `execute`.
- [ ] A leg with no deadline is admitted and renewed on a backend that declares a
  `max_lifetime_s`; an owner killed with SIGKILL leaves a sandbox that the next
  `phase-loop sandbox reap` kills, while a sandbox under a live lease survives.
- [ ] With `PHASE_LOOP_SANDBOX_REMOTE_REQUIRED=1`, a leg that ran through `execute`
  completes, and a leg every candidate refused ends with
  `sandbox_placement_required_unavailable` and zero spawns.
- [ ] With no remote root configured, plan 1a's local-equivalence golden matches unchanged.

## Maintainer decisions

**Settled (2026-10-10), cited and not restated:** the route is a self-hosted compute host
over SSH first, with this driver built first; the cloud backend follows as overflow; the
built-in egress list is left as it is. Standing rulings this plan relies on: R1 and R2
(agent-harness#1245); RD3, RD6 and CD1–CD4 (agent-harness#1162).

**Open for P1:** none. The admission wait defaults to off, and the fail-closed knob keeps
its present meaning, so P1 implements both answers to "what happens when the compute host
cannot take a seat"; which one a host uses is configuration.

**Open for P2 and P3:** listed in those plans.

## Execution Policy

- execute: effort=high, reason=changes the attested launch site and adds the first path on which a review tree and a leg leave the launching host
