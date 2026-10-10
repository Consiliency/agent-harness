---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1222, agent-harness#1166, agent-harness#1253, agent-harness#1162]
builds_on: [plans/detailed-remote-seat-placement-896-20261010.md, plans/detailed-ssh-placement-backend-896-20261010.md, plans/detailed-placement-reconnect-896-20261010.md, plans/detailed-seat-launch-factoring-896-20261010.md]
automation:
  suite_command: "cd phase-loop-runtime && PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placed_seat.py tests/test_placement_entry.py tests/test_placement_reconnect.py tests/test_sandbox_ssh.py tests/test_placement_driver.py tests/test_sandbox_placement.py tests/test_seat_sandbox_permissions.py tests/test_seat_preflight_1204.py tests/test_cli_qualification_contract.py tests/test_seat_notices.py tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py tests/test_harden_evidence_verifier.py tests/test_harden_evidence_producer.py tests/test_review_monitor_policy.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: the jailed Claude seat is placed on the compute host, and the driver flag turns on (agent-harness#896, P4)

## Task

After P1, P2, P2b and P3 the runtime has a driver, a transport, a far end that runs a null
workload and keeps it across a dropped connection, and a launch closure both hosts can
call. This unit makes one seat really run on
the compute host: the **jailed Claude seat**, the only seat that on main already runs under
its own leased subordinate uid. It adds the execute branch at the launch site, the leg
request and result, the far end's seat run, and turns `_NONLOCAL_EXECUTION_DRIVER` on.

It is one unit, not two, on purpose: with the flag on and a far end that cannot yet run a
seat, every opted-in user's Claude seat would be refused. The flag and the far end's seat
run land together.

Codex and grok are **not** placed by this unit; they run locally until P5
(`plans/detailed-placed-owned-seats-896-20261010.md`) gives them a seat uid on the compute
host. The Gemini seat is sealed and is not placed in this slice.

Cited, not restated: amendments C1–C12 (P1); the transport, entry point and host
qualification (P2); the keeper, the reconnect window and resume (P2b); `_infer_leg_here` and the credential source (P3); SEATJAIL and
SEATOWNER in `advisor_board/CONTRACTS.md`.

## Research summary

- **The launch site.** `_default_spawn` calls `_refuse_unless_executed_remotely(mode,
  executed_remotely=False)` **twice**: once before any root is selected or staged
  (`panel_invoker.py:11932`) and once at the launch boundary (`:12002`). The route is
  decided, and the login wait runs, before staging. The mode line is printed by
  `_seat_launch_modes` before launch.
- **Tests that pin flag-off behaviour** in `tests/test_sandbox_placement.py`: the execution
  gate test; the "refuses before prepare" group; the gated-fallback test; the
  fake-backend-never-called test. `tests/test_harden_evidence_verifier.py` holds a control
  that accepts a record with a non-local backend, runtime receipts and every local-launch
  key.
- **The jailed Claude seat.** `JAILED_LEGS` is `{"claude"}`. Its tree, `seat-home/` and
  `seat-out/` are host directories on disk, handed to the leased subordinate uid by
  `seat_uid.handoff`; normal teardown removes them through the live holder namespace. Its
  prompt is a pointer prompt that names jail paths only (`/seat/tree`, …), so it means the
  same on any host. Its token arrives on a pipe.
- **The Claude credential.** `resolve_claude_seat_credential` prefers a stored seat-token
  override, which is long-lived and has no expiry metadata, and otherwise uses the login's
  access token, which expires.
- **The verifier.** `verify_broker` raises the EC-HARDEN-5 UNMET residual as its first
  statement, before any key-set or placement check. The predicate (`harden5_unmet`) is true
  for a record whose prompt is not inline, among others. A local tooled codex record is
  accepted today.
- **The provider evidence.** `_record_broker_provider_evidence` writes fifteen keys about a
  launch on this host; `verify_broker` requires a further Claude set (session, transcript,
  liveness and task-request keys).
- **Failure details** are a closed vocabulary of fixed codes **and** typed templates (a
  reset time, an exit code, a signal number). The provider's raw output goes to a private
  per-leg log file, never into a record.

## Design

**Which legs are placed.** A leg is a placement candidate when all of these hold:
- review mode, a staged tree, the brokered branch;
- its harness is in the closed set `PLACED_HARNESSES`, which this unit sets to `{"claude"}`;
- its route is the jailed one;
- it is not deferred to the driving session and is not a capture-enabled qualification leg;
- its credential is placeable (below).

Any other leg runs locally exactly as today, with `sandbox_placement_leg_ineligible`
recorded when a remote root is configured. Under the fail-closed knob an ineligible leg is
refused, as today.

**The route decision for a candidate.** Decided before staging, as today, with one change:
the two steps that describe the **host** (jail capability, the jail's per-host
qualification) are deferred to the compute host, which answers them in `READY`. The
compute host runs the jail's first-use qualification inside host qualification, before
`READY`, never after `execute`; an unqualified host refuses in `admit`. The steps that
describe the **request and the login** (a staged tree, credential presence, the margin and
its wait) run on the launching host before staging, unchanged. If placement ends in the
local fallback (C7), the route is decided again from the local host's facts, and a sealed
outcome there means the seat is not run.

**The launch site.**
- The early knob check refuses only when no non-local candidate is configured for the leg;
  the launch-boundary check receives `executed_remotely=True` exactly when the leg is
  committed to a non-local backend.
- After both revalidations, `sandbox_placement.place` runs the C7 walk.
- For a placed leg no local egress namespace and no local seat id are acquired: nothing
  runs here. The local enforcement facts are recorded as not applied, with a reason naming
  the placement. (Only the Gemini route treats an unfiltered network as a refusal, and it
  is not placed.)
- `_parent_infer` calls `_exec_placed_leg` instead of `_infer_leg_here`. The broker and its
  probe client stay on the launching host.
- The reaper runs at the existing scratch-collection call site (C6).

**The request, `placement_leg_request.v1`.** Harness, model, effort, mode, monitoring
policy, timeouts; the bundle and instructions with their digests; the **sealed prompt as
the launching host rendered it**; the snapshot digest and the review-authorization fields
`_prepare_jailed_claude` reads; the credential slot; its own digest. The far end does not
render a prompt. The launching host records the digest of the prompt it sent.

**Credentials for a placed Claude seat** (rulings of 2026-10-10: the launching user's login,
per run; expiring subscription tokens only; a 30-minute floor).

| | Placed Claude seat |
|---|---|
| What the slot holds | `claudeAiOauth.accessToken` of the launching user's subscription login, and its `expiresAt`. Never the refresh token. **Never the stored seat-token override**, which does not expire. |
| A session with a stored override | The override is usable only while the session is logged in to the account it is bound to, so a subscription login exists. The placed seat gets that login's access token if it meets the floor. If it does not, the leg is not placed (`seat_placement_credential_under_floor`) and runs locally on the override, as today. The override's bytes never enter a request. |
| The floor | `PHASE_LOOP_SANDBOX_PLACED_TOKEN_FLOOR_S`, default 1800. There is no cap on lifetime. |
| When it is checked | Twice. Early, before staging, so a seat that cannot be placed costs no transfer. And, **bindingly, at the last moment**: from a fresh read immediately before the credential is sealed into the request, after the admission wait and the stage transfer. |
| Under the floor at the last moment | The launching host first uses the renewal it already has for this vendor: the read-only wait for the owner's own session to renew the login (`seat_credentials.await_login_margin`), up to its existing wait. It never uses the refresh token itself. Then it reads again. Still under: the sandbox is released with confirmation, the leg is recorded `seat_placement_credential_under_floor`, and the seat runs **locally**. Nothing was launched, so nothing moves. |
| Lifetime | Hours (measured on one host). |
| A seat that outlives its token | It is cut off only if it runs longer than the token had left. Main already types this for the jailed seat: an authentication failure at or after the token's expiry is `claude_seat_login_token_expired`. The far end is given the expiry and reports the same code. It is never a silent hang: once the expiry has passed, a seat with no progress for the stall window is ended with that code, under every monitoring policy. It is never re-run on another host. |
| On the compute host | The request is held in the entry point's memory and handed to the seat through the credential source of P3: the token goes on a drained pipe, exactly as locally. No login store is read there. |
| The seat's home | **On disk**, as locally: the jail's `seat-home/`, owned by the seat's subordinate uid. The runtime writes no credential there. What the CLI itself writes there is not known for the token; the live check below scans for it. |
| Destroyed on clean exit | At once, through the jail's mapped teardown |
| After the entry point is killed (signal, out-of-memory) | The seat dies with it. Its tree, home and output stay on disk until the next session of **any** principal, whose start sweep removes them through the mapped namespace (P2). The seat id is not leased again while they exist. |
| After a reboot | Memory is gone. The directories stay until the first session after boot. |

So for this seat "nothing at rest" is a limit, stated: **the runtime puts no credential in
any file on the compute host; a jailed seat's own directories are on disk while it runs and,
after a crash, until the next admission.** Core dumps are off and swap is zero for the
account (P2).

**Refreshing a token inside a running seat: a named follow-on, not built.** For Claude it
is not feasible as the seat is built today: the token is delivered once, on a pipe the CLI
drains at start, and nothing re-reads it; the seat's session may not be resumed. It would
need either support in the CLI for a second read or a new delivery channel into the jail,
and it would keep "no credential in a file" only if that channel stays in memory. The
trigger for building it is evidence: the count of `claude_seat_login_token_expired`
outcomes on placed seats, which the evidence already records per leg.

**The far end's seat run** (`workload="leg"`). It runs inside P2b's keeper, so a seat
survives a dropped connection for the reconnect window. That window never passes the
token's expiry or a bounded leg's deadline; the launching host puts both into the absolute
time C12 carries. The keeper rebuilds the staged
directory from the verified tree and the request; leases a seat id, from the one lock
directory the entry point fixed at start (P2), as the jail's own qualification does; builds the seat's egress namespace in the owner-pipe form for every
monitoring policy, with an empty private allowlist and `required=True`; and calls
`_infer_leg_here` with the request's credential slot as the credential source. A stand-in
for the review monitor turns the same progress observations the local loops make into
`PROGRESS` frames. `CANCEL` runs the leg's ordinary quiescence path before `KILLED`. A
measured bound on the sandbox's directories (RD5 (b)) kills a seat that exceeds it, with
`sandbox_placement_bound_exceeded`.

**The result, `placement_leg_result.v1`, and what the launching host does with it.**
- Status and text; a failure as a fixed code or as a template name with its typed fields;
  notices; the private leg log's bytes; one block of claims (the compute host's record of
  the launch shape, uid, capability sets, jail profile digest, egress report); the echo of
  the request digest.
- The launching host ingests under a size cap and a strict decode. A fixed code is kept only
  if it is in `_HARNESS_DETAIL_CODES`; a template is **re-validated and re-rendered here**
  from its typed fields; a notice is kept only if it is a `NOTICES` code. The leg log is
  written to the launching host's private leg-log file under the existing rules. Credential
  values registered for the leg are redacted here as well as there. Anything malformed is
  `sandbox_placement_result_invalid`.
- The claims are stored under one enumerated key. No gate, verifier or closeout reads it.

**The broker record of a placed seat, and the verifier.**
- It carries `provider_placement: <backend name>` and only what the launching host
  observed: `provider_harness`, `provider_model`, `provider_prompt_sha256`,
  `provider_prompt_bytes`, `provider_transport_sha256` and `provider_transport_bytes` (of
  the request), `provider_prompt_transport` with the fixed value `placement`, and the
  existing input and response keys.
- **Absent**, not filled from the far end: `provider_argv_shape`, `provider_argv_sha256`,
  `provider_cwd_class`, `provider_cwd_sha256`, `provider_env_keys`,
  `provider_env_api_keys_scrubbed`, `provider_env_direct_routes_scrubbed`,
  `provider_no_tool_controls`, and the whole Claude set `verify_broker` requires for a
  local launch (the session, transcript, liveness, task-request and route keys).
- The rule runs both ways: a record with `provider_placement` must have that non-local
  `sandbox_placement_backend` and zero local spawns; a record with a non-local
  `sandbox_placement_backend` must have `provider_placement`.
- **Check order.** For such a record `verify_broker` checks the closed key set and
  `verify_sandbox_placement` first, each with its own message, and evaluates the
  EC-HARDEN-5 predicate last. The predicate itself is not changed. A placed jailed Claude
  record has a pointer prompt, so it is reported UNMET, as the local jailed seat is.

**Mode.** A placed seat's mode is `remote`, with the backend name. The pre-launch mode line
shows it as the intended mode. `seat-modes.json` records the mode the seat actually ran in,
written after placement resolves, so a fallback shows as the local mode with its notice.

**Separation, proven through the jail's view.** Host qualification (P2) gains a probe
launched through the jail exactly as a Claude seat is, under a leased seat id. Given the
real values, it must fail to:
- list, open or stat another principal's sandbox, another sandbox of its own principal, the
  workspace root, and the entry point's configuration and state;
- see or signal the entry point's pid and a second sandbox's pid;
- connect to an abstract unix socket and to a pathname unix socket the entry point opened;
- attach a System V segment and open a POSIX message queue the entry point created;
- read a key in the account's user keyring;
- find any inherited descriptor beyond the declared set.

**CLI qualification.** The per-host CLI qualification of agent-harness#1333 is inert on
main. When it becomes active it must run on the host whose CLI the seat uses; until then
`READY` reports each placed CLI's path, digest and version as claims, and the launching
host's own CLI says nothing about the compute host's.

**Where trust rests, stated plainly.** The review text is produced on the compute host. Its
operator, and root there, can read the tree, the token in memory and the output, and can
also write: a forged result passes every rule here. With one account the same holds for
anything that gains that account. That is the residual accepted under RD4 (a) and ruling
B6. The claims are unsigned: the signature is deferred by the ruling on Q3.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_NONLOCAL_EXECUTION_DRIVER` — modify — `True`.
- `PLACED_HARNESSES`, `_placeable(...)` — add — the candidate rule.
- `_default_spawn` — modify — both knob call sites; the C7 walk after both revalidations;
  no local egress or seat id for a placed leg; the reaper at the scratch-collection call
  site; the `finally` releases through C11.
- `_seat_route_for_spawn` call site — modify — defers the two host steps for a candidate;
  decides again on fallback; a sealed outcome on fallback is not run.
- `_exec_placed_leg` — add — builds the request, calls `run_placed`, feeds `ExecProgress`
  to the review monitor, maps the broker latch's cancel to the backend, ingests the result.
- `execute_leg_request(request, tree, *, on_progress, cancelled)` — add — the far end's
  seat run.
- `_placement_request` — modify — `deadline_s=None` under a review monitor; the fields C5,
  C6 and C10 add.
- The broker's provider evidence — modify — the placed shape.
- `_record_sandbox_facts` / `_sandbox_evidence` — modify — `sandbox_placement_created_at`,
  `sandbox_placement_confirmed_killed_at` and the claims key for a placed leg.
- `_seat_launch_modes` and the `seat-modes.json` writer — modify — the intended and the
  actual mode.
- `_HARNESS_DETAIL_CODES` — modify — add `sandbox_placement_leg_ineligible`,
  `sandbox_placement_result_invalid`, `sandbox_placement_bound_exceeded`,
  `seat_placement_credential_not_placeable`, `seat_placement_credential_under_floor`.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … a HARNESS CODE — a fixed string this
  runtime itself emits (`_HARNESS_DETAIL_CODES`)". Members are added by that mechanism; no
  template or category is added.

### `phase-loop-runtime/src/phase_loop_runtime/placement_leg.py` (create)
- The request and result codecs and `ingest_result` — add.
- `PlacedCredentialSource` — add — a `SeatCredentialSource` (P3) backed by a request's slot.

### `phase-loop-runtime/src/phase_loop_runtime/placement_entry.py`, `sandbox_ssh.py` (modify)
- `workload="leg"` — modify — admitted for a harness the far end reports it can place;
  runs `execute_leg_request`; the seat-id lease directory from configuration; the measured
  bound; the sweep's refusal to lease a seat id whose residue exists.
- Host qualification — modify — the jail's first-use qualification and the separation
  probe through the jail's view; `READY` reports the harnesses it will place.

### `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `seat_jail.py`, `cli.py` (modify)
- `SEAT_MODES` — modify — add `remote`, unless agent-harness#1244's PR-A1 landed first and
  added it; `SeatMode` — modify — a `placement` field.
- `NOTICES` — modify — a row for each code added above.
- `placement qualify <name> --seat claude` — add — one minimal real seat through the whole
  placed path with the operator's own login. It records the vendor's response and scans
  the real seat home, output and tree on the compute host for the token's value before
  teardown. An operator command; it never runs in CI.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)
- `verify_broker` — modify — the placed key set, the two-way rule and the check order
  above.
- `SANDBOX_OPTIONAL_KEYS` — modify — the two timestamps and the claims key, enumerated.

### `phase-loop-runtime/tests/test_placed_seat.py` (create); `tests/test_sandbox_placement.py`, `tests/test_harden_evidence_verifier.py`, `tests/test_placement_entry.py`, `tests/data/seat_launch_references.json`, `tests/test_agent_cli_scratch_inventory_1147.py` (modify)
- The falsifiers under "Verification".
- **Changed existing tests, each replaced and listed in the PR body:** in
  `tests/test_sandbox_placement.py`, the execution gate test, the "refuses before prepare"
  group, the gated-fallback test and the fake-backend-never-called test; in
  `tests/test_harden_evidence_verifier.py`, the control that accepts a non-local backend
  with local-launch keys, which the two-way rule now rejects.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify — the
  execution-gate and fail-closed paragraphs (the flag is on; the early refusal applies only
  when no non-local candidate is configured); which legs are placed; the placed route
  decision; the request and result; the placed broker record; the `remote` mode; under
  SEATOWNER and SEATJAIL, the credential table above.
- `docs/phase-loop/remote-seat-host.md` — modify — the Claude CLI at the launching host's
  version, the jail qualification on the compute host, and that no login is ever performed
  there.
- `docs/phase-loop/convergence-runtime.md` — modify — replace "This release has no driver
  that executes on a non-local backend"; the admission wait and what the knob now exempts.
- `docs/advisor-board-capabilities-card.md` — modify — the `remote` mode, what its evidence
  does and does not prove, and where a placed seat's duration is recorded (ruling R2).
- `phase-loop-skills/advisor-board/SKILL.md` — modify — one line on the `remote` mode.
  Regenerate with `phase-loop-runtime/scripts/regenerate_skills_bundle.py`, then
  `sync_skills_bundle.py`.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none.

## Dependencies & order
1. Needs P1, P2, P2b and P3 merged.
2. It edits the launch site, which the 0.7.27 seat fixes also edit; it starts from a base
   that contains them.
3. agent-harness#1244's PR-A1 moves route selection into a resolver and owns the `remote`
   literal. Whichever lands second adapts; the substance does not change.
4. No agy route-core file is edited. Nothing a seat sandbox permits changes: the jail on
   the compute host is the jail on main. The seat-jail profile digests and the falsifier
   layout identity are recorded before and after and must be equal.
5. Order: the codecs and `ingest_result`; the verifier; `_default_spawn` with tests that
   force the flag; the far end's seat run; host qualification; then the flag, last.

## Verification

```sh
cd phase-loop-runtime
PHASE_LOOP_REQUIRE_SSHD=1 PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_placed_seat.py tests/test_placement_entry.py tests/test_placement_reconnect.py \
  tests/test_sandbox_ssh.py tests/test_placement_driver.py tests/test_sandbox_placement.py \
  tests/test_seat_sandbox_permissions.py tests/test_seat_preflight_1204.py \
  tests/test_cli_qualification_contract.py tests/test_seat_notices.py \
  tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py \
  tests/test_agent_cli_scratch_inventory_1147.py tests/test_launchspec_golden.py \
  tests/test_harden_evidence_verifier.py tests/test_harden_evidence_producer.py \
  tests/test_review_monitor_policy.py
ruff check .
```

Run on Python 3.12 and 3.10. The compute host in tests is the entry point on the same
machine, over a pipe and over P2's loopback `sshd` fixture, **with its own home, login
store and state**, a stand-in Claude CLI in the style of the existing seat tests, and
login fixtures in the CLI's real file shapes. Tests that need the jail skip, with the
existing reason, where the host lacks its prerequisites. Each case is control-green and
red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Nothing configured | Plan 1a's local-equivalence golden and the launch-spec golden match; the jail profile digests and falsifier layout identity are equal before and after | — |
| A placed Claude seat, end to end | Zero local provider spawns; runtime `committed` and `completed`; `sandbox_root_applied=true`; mode `remote`; the answer ingested | Build `completed` from the backend's receipt |
| The far end has its **own, different** Claude login and stored override | The placed seat uses the slot's token; a spy records no read of the far end's stores | Resolve the credential on the far end |
| The launching session would use a stored override | The slot holds the login's access token and never the override's bytes | Place whatever the resolver returns |
| Login token under the floor before staging, override present | Not placed: `seat_placement_credential_under_floor`; nothing is staged remotely; runs locally on the override | Refuse the seat outright |
| Token with 31 minutes left before staging and 29 at the last moment (the admission wait and the transfer took the difference); the owner's session does not renew it | Released with confirmation; `seat_placement_credential_under_floor`; the seat runs locally; no `execute` was called | Check the floor only before the session opens |
| The same, but the owner's session renews the login during the read-only wait | The fresh token is sealed and the seat is placed; the refresh token was never read | Refresh with the refresh token |
| A login with no readable expiry | Not placed: `seat_placement_credential_not_placeable` | Treat a missing expiry as far in the future |
| A placed seat whose token expires mid-run, then: an authentication failure; silence for the stall window | Both end as `claude_seat_login_token_expired`, under heartbeat-only as well; no re-run on any host | Leave a silent seat running after expiry |
| The encoded request | Contains no refresh-token value and no override value | Narrow on the far end |
| During a placed seat, and after a clean exit | No file under the entry point's workspace, state, home or temporary directories holds the token value | Write the slot to a temporary file |
| Entry point killed with SIGKILL during a placed seat; then a session of a **different** principal | No seat process and no egress holder remains; that session's sweep removes the tree, home and output owned by the subordinate uid; until then the seat id is not leased | Sweep through the account uid; reuse the seat id at once |
| Separation probe through the jail's view, with a second principal's seat running | Every item in the Design list fails for the probe | Drop the pid namespace; drop the IPC namespace; launch outside the filtered namespace; bind the workspace root; give two seats one uid |
| Two principals: A runs arbitrary code as its seat while B's seat runs | A cannot read B's token, tree or output; nothing A leaves is read or executed in B's next session | Reuse a run directory; read configuration from the home |
| Sealed-route leg; codex and grok; capture-enabled leg; a leg deferred to the driving session | Not candidates; `sandbox_placement_leg_ineligible`; run locally as today; under the knob, refused | Place every leg |
| Launching host with no jail capability, compute host with it | The Claude seat is placed and runs jailed there | Decide the route from the launching host's capability |
| Compute host whose jail qualification fails | Refused in `admit` as `sandbox_ssh_host_unqualified`; not run; never after `execute` | Qualify after `execute` |
| C7 outcomes through `_default_spawn`: at capacity; at capacity then unreachable; unreachable; not enrolled; host key mismatch | Waits then not run; not run; local with the loud record; not run; not run | Run locally for any but unreachable |
| Local fallback where the local route is the sealed one | Not run | Run sealed |
| Under the knob: no non-local candidate; a candidate that admits; every candidate unreachable | Refused early; completes; refused with zero spawns | Keep the early refusal unconditional |
| Heartbeat-only seat that keeps producing output; one waiting at the cap | `PROGRESS` reaches the review monitor and no deadline applies on either side; `placement_wait` is recorded and no stall notice is raised while it waits | Start the stall clock at `admit` |
| Cancel from the launching host | The far end's quiescence path runs; `KILLED` only after it | Kill without quiescence |
| Connection dropped during a placed seat; resumed inside the window | The seat never stopped; the answer arrives complete; one `completed` receipt; mode `remote` | Start the seat again |
| Connection dropped; no resume | The keeper ends the seat at the window's end: the jail's mapped teardown removes the tree, home and output; no token remains in any process; the slot is free; the leg is `sandbox_placement_lost_after_launch` and is not run anywhere else | Leave the seat's directories for the next sweep |
| Connection dropped with a token that expires in ten minutes and a 30-minute window | The seat is ended at the token's expiry, not at the window's end | Keep for the full window |
| A seat that writes past the measured bound | Killed with `sandbox_placement_bound_exceeded`; other seats continue | Measure once at start |
| Result with, in turn: a code outside the vocabulary; a usage-limit template; an unknown notice; a wrong request-digest echo; a credential value in the text | In turn: the unknown-failure template; the template re-rendered locally from its fields; the notice dropped; `sandbox_placement_lost_after_launch`; redacted | Trust the result's rendered detail |
| Verifier, conformant placed record | `verify_sandbox_placement` accepts it; `verify_broker` raises the EC-HARDEN-5 residual and nothing else | Evaluate the predicate first |
| Verifier, in turn: `completed` from the backend; one local-launch key present; a non-local backend with no `provider_placement`; `provider_placement` with local spawns | Each raises its own shape or placement message, not the residual | Skip the shape check for placed records |
| Mode | The mode line shows `remote`; after a fallback `seat-modes.json` records the local mode | Record the intended mode |

**Live check, outside CI.** `phase-loop placement qualify <name> --seat claude`, then one
board from a launching host against a real compute host with `heartbeat_only` monitoring.
Recorded in the PR: the vendor's response to a login used from the compute host's address;
the scan of the real seat home for the token; mode `remote`; no Claude seat process on the
launching host; `placement qualify` passing before and after.

## Acceptance criteria
- [ ] Through the loopback fixture a placed Claude seat records zero local provider spawns
  and `sandbox_root_applied=true`; `verify_sandbox_placement` accepts its record and
  `verify_broker` raises only the EC-HARDEN-5 residual; with `completed` taken from the
  backend it raises the placement message instead.
- [ ] With a different Claude login and override in the far end's own stores, the placed
  seat uses the slot's token and reads neither; the encoded request holds no refresh token
  and no override.
- [ ] An entry point killed during a placed seat leaves directories that the next session
  of a different principal removes, and the seat id is not leased before that.
- [ ] The separation probe, run through the jail's view beside another principal's seat,
  fails on every item listed under Design, and passes its mutations only when they are
  applied.
- [ ] With nothing configured, plan 1a's local-equivalence golden and
  `tests/test_launchspec_golden.py` pass unchanged; with a remote root configured, codex,
  grok and Gemini seats run locally as today.

## Maintainer decisions

**Rulings of 2026-10-10** (relayed by the team lead):

| Ruling | What it fixes in this plan |
|---|---|
| Logins (B1): the launching user's, per run, in the access-only form, nothing at rest | The credential table. Its disclosed risks and their checks are below. |
| Credentials: expiring subscription tokens only; a 30-minute floor checked at the last moment; mid-run refresh a named follow-on | The credential table and the follow-on paragraph |
| Accounts (B6): one shared account first; separation rests on the sandbox and a probe | The separation probe and the two-principal test are acceptance criteria |
| Busy or down (B3) | C7, exercised here through `_default_spawn` |
| Scope (B4): seats only | `_placeable` |

**Known risks, disclosed with ruling B1, each with its check:**

| Risk | Check |
|---|---|
| Root on the compute host can read a token in memory while a seat runs, and can forge a result | Cannot be prevented, only bounded: the token expires (the override is never placed); no credential is written by the runtime; the mode line and operator guide state it |
| A seat runs longer than its token had left | Typed (`claude_seat_login_token_expired`), never a silent hang, never re-run elsewhere; the count of such outcomes is the trigger for the refresh follow-on |
| A vendor may object to a login used from the compute host's address | `placement qualify --seat claude` records what the vendor did; a refusal makes the harness ineligible until resolved |
| A jailed seat's own directories are on disk after a crash until the next admission | The kill-then-different-principal case; the live scan for the token in the real seat home |

**Open:** none. The claims this unit returns are unsigned by the maintainer's ruling of
2026-10-10 (Q3: the signature is deferred, not dropped); no gate, verifier or closeout may
read them until that follow-on lands.

## Execution Policy

- execute: effort=max, reason=turns the driver on and moves a real seat and a vendor token across hosts; the launch site, the verifier and the credential path all change
