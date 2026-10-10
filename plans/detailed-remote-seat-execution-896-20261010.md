---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: 570bdda0
related_issues: [agent-harness#896, agent-harness#1244, agent-harness#1222, agent-harness#1166, agent-harness#1253, agent-harness#1162]
builds_on: [plans/detailed-remote-seat-placement-896-20261010.md, plans/detailed-ssh-placement-backend-896-20261010.md]
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' tests/test_placed_seat.py tests/test_placement_entry.py tests/test_sandbox_ssh.py tests/test_placement_driver.py tests/test_sandbox_placement.py tests/test_seat_notices.py tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py tests/test_launchspec_golden.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_harden_evidence_verifier.py tests/test_review_monitor_policy.py"
  verification_status: not_run
  human_required: true
---

# Detailed plan: a review seat executes on the compute host through the placement entry point (agent-harness#896, P3)

## Task

P1 gives the runtime a driver and P2 a transport and a far end that runs a null workload.
This unit makes the far end run a **seat**: the same launch path a local seat takes, with
the launching user's own narrowed login delivered for that one run, and the result ingested
on the launching host. After it, a board's tooled seats execute on the compute host.

It cites, and does not restate: the seam and amendments C1–C9
(`plans/detailed-remote-seat-placement-896-20261010.md`); the transport and entry point
(`plans/detailed-ssh-placement-backend-896-20261010.md`); SEATOWNER and SEATJAIL in
`advisor_board/CONTRACTS.md`.

## Research summary

- **The unit to move.** In `panel_invoker._default_spawn`'s brokered branch the provider is
  launched from the `_parent_infer` closure, which calls `_prepare_jailed_claude` and
  `_exec_jailed_claude_leg`, or `_exec_claude_tui_leg`, or `_exec_leg`, and folds their
  failure details and notices. Its inputs are the staged directory (bundle, instructions,
  tree), the sealed prompt, the model and effort, timeouts, the review monitor, a quiescence
  latch, the leg's egress prefix and seat id, and the review authorization. The broker and
  its probe client are separate from that closure and stay on the launching host.
- **Credentials are read in one place.** `panel_invoker.seat_profile` copies the narrowest
  form of each login into a per-launch private home built from memory-backed descriptors:
  codex's auth file with the refresh token blanked and a one-line config; grok's
  access-token-only auth file and its agent id; agy's access-only token and settings, after
  a refresh on the host; Claude's token on a drained pipe, chosen by
  `seat_credentials.resolve_claude_seat_credential` (the session binding of
  agent-harness#1253). It reads the operator's home through `_seat_credential`.
- **The route decision takes its host facts as arguments.** `seat_jail.decide_seat_route`
  has an injectable `capable`, and `_seat_route_for_spawn` an injectable
  `qualify_on_first_use`.
- **Evidence.** `_record_broker_provider_evidence` writes the local launch shape into the
  broker record; amendment C6 keeps those keys out of a placed leg's record.
- **Modes.** `seat_preflight.SEAT_MODES` is a closed tuple with no `remote`.
  agent-harness#1244's PR-A1 plans to add the literal and has not landed.

## Design

**Same code, other host.** The body of `_parent_infer` becomes one function that both sides
call. On the launching host nothing changes. On the compute host the entry point rebuilds
the staged directory from the verified tree and the request, acquires the seat's egress
namespace and seat id **there**, and calls the same function. No second launch path and no
second confinement is written.

**Which legs are placed.** A leg is placed when all of these hold; otherwise it runs
locally with the recorded reason `sandbox_placement_leg_ineligible`, or is refused under
the fail-closed knob:
- review mode, a staged tree, and the brokered branch;
- its route is a tooled one (the jailed route, or the staged tool-enabled route). A leg
  whose route is the sealed inline one is not placed in this slice;
- it is not deferred to the driving session, and is not a capture-enabled qualification
  leg.

**The route decision for a placed leg.** The steps that describe the **host** (jail
capability, the jail's per-host qualification) are answered by the compute host, at
admission and at launch, through the injectable arguments above. The steps that describe
the **request and the login** (a staged tree, credential presence, the login's margin and
its wait) are answered on the launching host, before anything is sent. If placement falls
back to local, the route is decided again with the local host's facts.

**Credentials (assumes B1 (a); RD4 (a) and CD1 as ruled).**
- The narrowing in `seat_profile` is factored into one function. Locally it reads the
  operator's home, as today. For a placed leg the launching host calls it, including
  Claude's session-binding decision and agy's refresh, and puts the result in the request's
  credential slot: a map of relative path to bytes, and the Claude token.
- On the compute host `seat_profile` takes its bytes from that slot through a
  credential-source context instead of a home directory, and builds the private home
  exactly as locally: memory-backed descriptors, the token pipe. It reads no login store
  there, performs no refresh there, and writes none of it to a file system.
- The slot never contains a refresh token. Every secret value in it is registered for
  redaction on both sides.
- The request travels only on the one-shot channel (C1). The entry point holds it in
  memory and drops it when the seat ends.

**Liveness and cancel.** On the compute host a review-monitor stand-in turns the same
progress observations the local loops make into `PROGRESS` frames. The stall notice and,
for bounded legs, the stall kill are decided on the launching host from those frames. A
cancel on the launching host's latch becomes `CANCEL`, and the compute host runs the leg's
ordinary quiescence path before it answers `KILLED`.

**What comes back.** Status, text, the failure detail and notices (kept only if they are
members of the closed lists, per C6), and two blocks of **claims**: the provider launch
shape the compute host recorded, and its identity facts (uid, capability sets, the jail
profile digest, the egress enforcement report, the runtime's version and wheel digest).
Claims are stored under one enumerated evidence key that no gate, verifier or closeout
reads. EC-HARDEN-5 stays UNMET for a placed tooled seat, as for a local one.

**Where trust rests, stated plainly.** The review text is produced on the compute host. Its
operator, and root there, can read the tree, the login bytes in memory and the output. That
is the residual ruled acceptable under RD4 (a); it is the same trust the launching host's
root already has.

**Mode.** A placed seat's mode is `remote`, with the backend name, shown in the pre-launch
mode line and recorded in `seat-modes.json`.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` (modify)
- `_infer_leg_here(...)` — add — the body of `_parent_infer`, moved without change;
  `_parent_infer` — modify — delegates to it, or to P1's `_exec_placed_leg` for a placed leg.
- `_narrow_seat_credentials(...)` — add — the credential narrowing factored out of
  `seat_profile`; `seat_profile` — modify — consumes it from the home or from the
  credential-source context; with the context set it skips the host refresh and reads no
  host file.
- `execute_leg_request(request, tree, *, on_progress, cancelled)` — add — the compute-host
  side described under Design. It builds the egress namespace with `required=True`.
- `_placeable(...)` — add — the eligibility rule.
- `_seat_route_for_spawn` call site — modify — passes placement-answered `capable` and
  `qualify_on_first_use` for a leg with a non-local candidate; decides again on fallback.
- `_exec_placed_leg` — modify — fills the credential slot; maps the returned claims to the
  evidence key.
- `_HARNESS_DETAIL_CODES` — modify — add exactly `sandbox_placement_leg_ineligible`.

  **Frozen vocabulary, quoted from `panel_invoker.py:2837-2840`:** "`PanelLegResult.detail`
  is built ONLY from our own closed vocabulary. … a HARNESS CODE — a fixed string this
  runtime itself emits (`_HARNESS_DETAIL_CODES`)". One member is added by that mechanism,
  and no template or category.

### `phase-loop-runtime/src/phase_loop_runtime/placement_leg.py` (modify)
- The request's credential slot, and the fields of the review authorization that
  `_prepare_jailed_claude` reads — modify — carried as data; no authorization is minted on
  the compute host.
- The result's two claim blocks — add.

### `phase-loop-runtime/src/phase_loop_runtime/placement_entry.py` (modify)
- `kind="leg"` — modify — calls `execute_leg_request`.
- The host probe — modify — also reports which vendor CLIs are present and whether the agy
  image is an admitted one. It performs no login and starts no model call.

### `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `seat_jail.py` (modify)
- `SEAT_MODES` — modify — add `remote`, unless agent-harness#1244's PR-A1 has landed first
  and already added it; `SeatMode` — modify — a `placement` field.
- `NOTICES` — modify — a row for `sandbox_placement_leg_ineligible`.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)
- `SANDBOX_OPTIONAL_KEYS` — modify — the one claims key, enumerated; the verifier checks
  its type and reads nothing from it.

### `phase-loop-runtime/tests/test_placed_seat.py` (create); `tests/test_placement_entry.py`, `tests/test_harden_evidence_verifier.py`, `tests/data/seat_launch_references.json` (modify)
- The falsifiers under "Verification". Moving `_parent_infer`'s body changes the function
  each launch reference is counted under; the inventory is updated and the PR body lists
  every moved row.

## Documentation impact
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` — modify —
  SEATOWNER: the credential source for a placed seat, and that no login store is read on
  the compute host; the placement seam: which legs are placed, the placed route decision,
  the claims key; the `remote` mode.
- `docs/phase-loop/remote-seat-host.md` — modify — vendor CLIs at the launching host's
  versions, the agy admitted-image rule, the jail qualification, and that no login is ever
  performed on the compute host.
- `docs/advisor-board-capabilities-card.md` — modify — the `remote` mode and what its
  evidence does and does not prove.
- `phase-loop-skills/advisor-board/SKILL.md` — modify — one line on the `remote` mode.
  Regenerate with `phase-loop-runtime/scripts/regenerate_skills_bundle.py`, then
  `sync_skills_bundle.py`.
- `CHANGELOG.md` — modify — one entry under `## [Unreleased]`.
- `README.md`, `AGENTS.md`, `docs/TEAM-ONBOARDING.md` — none.

## Dependencies & order
1. Needs P1 and P2 merged.
2. It edits `panel_invoker.py`'s launch site and `seat_profile`, which the 0.7.27 seat
   fixes also edit. It starts from a base that contains them.
3. agent-harness#1244's PR-A1 moves route selection into a resolver and owns the `remote`
   literal. Whichever lands second adapts: the placed route decision moves into the
   resolver's step 2, unchanged in substance.
4. No agy route-core file is edited (`gemini_heartbeat.py`, `agy_qualification.py`,
   `agy_provenance.py`). If the agy refresh cannot be called from the factored narrowing
   without editing one, the implementer stops and reports before editing it.
5. The sandbox's binds, capabilities, namespaces and network rules are not changed. The
   seat-jail profile digests and the falsifier layout identity are recorded before and
   after and must be equal.
6. Order: the two factorings first, each alone, with the local-equivalence golden and the
   launch-spec golden unchanged; then the credential slot; then `execute_leg_request`; then
   eligibility and the route call site; then the mode and evidence.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python -m pytest -q -m 'not dotfiles_integration' \
  tests/test_placed_seat.py tests/test_placement_entry.py tests/test_sandbox_ssh.py \
  tests/test_placement_driver.py tests/test_sandbox_placement.py tests/test_seat_notices.py \
  tests/test_seat_owner_notices.py tests/test_seat_reference_inventory.py \
  tests/test_launchspec_golden.py tests/test_agent_cli_scratch_inventory_1147.py \
  tests/test_harden_evidence_verifier.py tests/test_review_monitor_policy.py
ruff check .
```

Run on Python 3.12 and 3.10. The compute host in tests is the entry point on the same
machine, over a pipe and over the loopback `sshd` fixture of P2, with stand-in provider
CLIs in the style of the existing seat tests and login fixtures in the CLIs' real file
shapes. Each
case is control-green and red under its mutation.

| Case | Expected | Mutation that must turn it red |
|---|---|---|
| Factoring only, nothing configured | Plan 1a's local-equivalence golden and the launch-spec golden match unchanged; the jail profile digests and the falsifier layout identity are equal before and after | Reorder egress acquisition and the launch |
| A placed codex, grok and Claude seat, end to end | The seat's private home on the far end holds byte-for-byte what a local seat's holds for the same login fixture; the answer is ingested; zero local provider spawns; `sandbox_root_applied=true` | Forward the unnarrowed auth file |
| The encoded request | Contains no refresh-token value from any fixture | Narrow on the far end instead of before sending |
| During and after a placed seat | No file under the entry point's workspace, home, or temporary directories contains a credential value | Write the slot to a temporary file |
| A Claude override stored under another account; a login with too little margin | Refused on the launching host exactly as for a local seat, before any session is opened | Resolve the credential on the far end |
| A credential value echoed by the stand-in provider | Redacted in the returned text on the launching host | Register redactions on the far end only |
| Sealed-route leg; capture-enabled leg; leg deferred to the driving session | Not placed; `sandbox_placement_leg_ineligible` recorded; under the knob, refused with zero spawns | Place every leg |
| Launching host with no jail capability, compute host with it | The Claude seat is placed and runs jailed there | Decide the route from the launching host's capability |
| Compute host with no recorded jail qualification | Qualified there on first use, or the seat is not run with the existing typed code; never sealed | Skip the gate for a placed leg |
| Placement falls back to local | The route is decided again from the local host's facts | Reuse the placed decision |
| Heartbeat-only seat that keeps producing output | `PROGRESS` frames reach the launching host's review monitor; no deadline is applied on either side | Apply the bounded stall kill |
| Cancel from the launching host | The far end's ordinary quiescence path runs; `KILLED` only after it | Kill without quiescence |
| Result carrying, in turn: a detail outside the vocabulary; an unknown notice; a claim block of the wrong type | In turn: the detail becomes the unknown-failure template; the notice is dropped; the result is refused as `sandbox_placement_result_invalid` | Trust the result's fields |
| Broker record of a placed seat | Passes the verifier's placed shape; reported EC-HARDEN-5 UNMET; the claims key is present and unread | Copy a claimed launch key into the record |
| Mode line | `remote` with the backend name for a placed seat; unchanged for a local one | Report `jailed` for a placed seat |

**Live check, outside CI.** One board from a launching host against a real compute host,
with real CLIs and `heartbeat_only` monitoring, recorded in the PR: each tooled seat shows
mode `remote`, the launching host's process table shows no provider CLI for those seats,
and `phase-loop sandbox qualify` passes before and after.

## Acceptance criteria
- [ ] With nothing configured, plan 1a's local-equivalence golden and
  `tests/test_launchspec_golden.py` pass unchanged, and the seat-jail profile digests and
  the falsifier layout identity are equal before and after the change.
- [ ] For each of codex, grok and Claude, a seat placed through the loopback fixture
  receives a private home byte-identical to a local seat's for the same login fixture,
  records zero local provider spawns, and yields `sandbox_root_applied=true`.
- [ ] No refresh-token value appears in any encoded request, and no credential value appears
  in any file under the entry point's directories during or after a placed seat.
- [ ] A Claude override bound to another account is refused on the launching host before
  any session is opened.
- [ ] A sealed-route leg is not placed, and under the fail-closed knob it is refused with
  zero spawns and is not run sealed.

## Maintainer decisions

**Settled, cited:** the route (2026-10-10); RD4 (a) and CD1 (agent-harness#1162); the
session binding of agent-harness#1253.

**Open, and what this plan assumes until they are ruled:**

| ID | Question | Assumed here | If ruled otherwise |
|---|---|---|---|
| B1 | Whose vendor login a placed seat uses | The launching user's own, per run, never at rest on the compute host | A login held on the compute host removes the credential slot and breaks the "no credential at rest" invariant; this plan would have to be rewritten, not adjusted |
| B4 | Whether the president or executors move in this slice | Seats only (RD3 as ruled) | The president is an addition to `_placeable` and the request; executors need their own plan |
| B2, B3 | The default on a shared launching host; behaviour when the compute host cannot take a seat | Configuration only: the root, the admission wait and the fail-closed knob already express every option | No code change |

## Execution Policy

- execute: effort=max, reason=moves the attested seat launch and vendor credentials across hosts; a behaviour-preserving refactor of the launch site and the credential path must be proven byte-identical first
