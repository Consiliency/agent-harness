---
phase_loop_plan_version: 1
phase: CLOSEOUT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 8aeebdf2c0a00b82df75e3af6ef1d4593073a1979bec1f2ed04e977e299cf005
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seats_closeout_seat_routes.py", "phase-loop-runtime/tests/test_sealed_seat_never_counts.py", "phase-loop-runtime/tests/test_seats_closeout_president.py", "phase-loop-runtime/tests/test_president_wiring.py", "phase-loop-runtime/tests/test_president_ladder_config.py", "phase-loop-runtime/tests/test_president_heartbeat_1001.py", "phase-loop-runtime/tests/test_seats_closeout_ledger.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# CLOSEOUT: Local Closeout

## Context

This plan covers roadmap Phase 11 (CLOSEOUT) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Acceptance is EC-CLOSEOUT-1 to EC-CLOSEOUT-4, cited by ID only. Every other
SEATS phase plan is on main; this plan consumes their ECs and records, and restates none.

**Execution gate.** Plan now. SL-1 and SL-2 may be implemented and reviewed as draft PRs after
E1-E5. Neither merges until OD-8 is recorded. The OD-8 request cites SL-2's draft-head V2
receipt and the president rows that draft produces. SL-3 may start its ledger and roll-up as
soon as this plan lands, but it settles no row before that row's owner phase has exited.

**Inputs.** The roadmap is pinned in the frontmatter, checked with `_sha256_file`. Every other
input is read by content on the lane's base tree, never pinned by digest here:
`plans/evidence/seat-inventory/index.json`, `plans/evidence/seat-inventory/dispositions.json`,
the TEAMHOST and caps contracts, the owner phases' decision records and window records. No lane
pins a SHA this phase will create.

**Owner rulings in force (2026-11-06).**

- The owner's designated standard host is the only sandboxed review-seat host, run by one
  operator. The owner's private roster names it (OD-C1). The shared developer host is being unloaded: it is not a seat host, and no CLOSEOUT live step,
  window or `VD` run takes place on it. The public text names host classes only (principle 8).
- Capacity offload ships disabled on every host. CLOSEOUT adds no `CapacityGrant` and no
  private host policy. The final matrix records "capacity offload: disabled" for each host
  class.
- Per-seat caps come before local enforcement. SL-1 removes the last unconfined route, which
  makes the jail the only local route, so SL-1 lands only after JAILCORE SL-5 is on main and
  its `VC` probe has passed (not skipped) on the seat host (entry check E3).

**Entry checks (by content, on the lane's base tree).**

- E1. INVENTORY, CLAUDENET, CODEX, GROK, PI and CLAUDETUI have exited. Every vendor row is
  `done-local`, is `done-remote` as EC-CLOSEOUT-2 admits, or is `remote-pending` under an OD-9 record with a typed-degraded interim route
  and an open REMOTE tracking issue; no vendor row is `candidate`. CLAUDETUI exits under OD-6
  and has no `remote-pending` path.
- E2. `dispositions.json` has an empty `pending_actions`. Its four rows at the input pin belong
  to EC-CLAUDE-2, EC-CLAUDE-3 and EC-CLAUDETUI-1. If a row remains, STOP. Report
  agent-harness#1740 or agent-harness#1744 to CLAUDE, and agent-harness#1641 or
  agent-harness#1623 to CLAUDETUI; the relevant owner phase must move it before exit.
- E3. `seat_resource_caps.py` exists, the caps test passes, and the passing, non-skipped
  seat-host-class `VC` receipt is recorded on the JAILCORE SL-5 landing PR.
- E4. Every carried-forward item below is met in its owner's landing.
- E5. Each named matrix exception (Claude open egress, Codex unconfined, Grok unconfined) has
  ended on the lane's base tree: its owner phase has exited, or its matrix expiry has passed
  and the row resolves typed-degraded. A renewal does not satisfy E5. SL-1 does not merge
  before E5; SL-3.2 records the ending in `exceptions.json`.

**Carried-forward items.** CLOSEOUT does not do the owner's work for these. It checks each one
in SL-3.2 and records the result in the roll-up. A miss STOPs SL-3 and is reported to the owner.

| Item | Owner | CLOSEOUT check |
|---|---|---|
| The unverified Grok tool surface case in the `seats_teamhost_agreement` table. agent-harness#1882 removed it from TEAMHOST. | GROK SL-2, through the explicit agreement-row amendment | The agreement table has a Grok case with an unverified tool surface; the doctor verdict is `refuses` with `grok_tool_surface_unverified`, never `admits` |
| Claude SDK fixture and receipt refresh in the caps work | JAILCORE SL-5 named edit, coordinated with CLAUDE (owner of both `launch-v1.json` copies and `plans/evidence/seat-qualification/claude-sdk-boundary/receipt-v1.json`) | On the base tree, `test_seats_claude_sdk.py` passes, including byte identity and owned capture, and the SDK receipt's `proof_inputs_sha256` is current. Otherwise STOP and report to JAILCORE and CLAUDE |
| Live agy requalification after TEAMHOST SL-3 | TEAMHOST SL-docs.6, the tracking item for the first post-TEAMHOST Gemini row-window PR (LA-3) | The Gemini row's latest window record was taken after TEAMHOST exited, and its `qualification_keys` equal the live EC-JAILCORE-4 key on the base tree |
| W0 | CLAUDE (LA-3), OD-3b | Records under `plans/evidence/seat-qualification/claude-w0/`; the OD-3b section of `plans/decision-claude-print-subscription-route-20261008.md` cites them |
| W1 | FIRSTSEAT | `plans/evidence/seat-qualification/W1.json` exists, and the Gemini row cites its digest |
| Vendor row windows | CLAUDENET, CODEX, GROK, PI, each for its own row | Each `done-local` row cites its row-window record under `plans/evidence/seat-qualification/` |
| CLAUDETUI `VD` runs | CLAUDETUI SL-1.3 | `plans/evidence/seat-tui/startup-diagnosis.json` exists, and the OD-6 section of `plans/decision-claude-print-subscription-route-20261008.md` cites its digest |
| OD-7 activations | REMOTE | Not required for local closeout. Each remote row is `done-remote` or `remote-pending` with an open REMOTE tracking issue (EC-CLOSEOUT-2) |
| agent-harness#1480 fallback removal for `review` seats | CODEX SL-3.8 | The CODEX decision record states the removal, and SL-1's falsifier finds no seat-launch-owner fallback path for a `review` seat |

**Index rows that no owner plan names.** These `owned` rows in `index.json` are not named in
the plan of their owning phase: agent-harness#848, agent-harness#1254, agent-harness#1287,
agent-harness#1391 (jailed-scope part), agent-harness#1419, agent-harness#1422,
agent-harness#1494, agent-harness#1531, agent-harness#1585, agent-harness#1653 (Grok part),
agent-harness#1682, agent-harness#1704 (seat-side part) and agent-harness#1774. SL-3.4 sweeps
them. A row whose owner EC holds on main gets a closure or comment citing the landing PR. A row
whose owner EC does not hold STOPs and is reported to that phase. CLOSEOUT itself owns
agent-harness#1132, agent-harness#1288, agent-harness#1244 (matrix part) and
agent-harness#1250.

## Interface Freeze Gates

- [ ] **IF-0-CLOSEOUT-1 — Seat route closure.** For a `review` seat, the seat-mode resolution
  in `panel_invoker.py` (the `seat_filesystem_unconfined` and "no file tools" branches) and
  every leg route return `jailed`, remote, native-fill or `degraded` with a code from
  `seat_jail.NOTICES`. `MODE_UNCONFINED` stays in `seat_preflight.SEAT_MODES` only so stored
  records parse; no review path emits it, including the `_default_spawn` Codex/Grok notice.
  `MODE_SEALED` is emitted only for non-review launches: an advisory run with no staged tree
  (`seat_sandbox_not_staged`), a non-brokered launch, and the agy qualification worker's
  candidate measurement. None counts as a review seat. SL-1 edits no name in
  `claude_seat_transport.SDK_PROOF_REGIONS`; a needed edit there STOPs and is reported to
  CLAUDE. The descend sets, `CAPACITY_CODES`, the profile builders and every profile digest
  stay byte-identical. No fix line names a removed route or an API-key lane.
- [ ] **IF-0-CLOSEOUT-2 — President rung routes.** `president_rung_inventory()` derives
  `tool_mode` from the same route resolver used by review seats, using the board's staged tree
  while preserving the president operation and decision grammar. A jailed or active-remote
  route is `tooled`; `native_fill_deferred` is `tooled` when fulfilled by the tool-using native
  president; every other result is `degraded` with its typed code. The sealed commands at the
  base—the tools-off `_run_claude_print_session` president call, the TUI president session, and
  `_exec_leg` in a throwaway directory—are removed under agent-harness#1250. A degraded rung
  writes its start entry and typed outcome, and the ladder advances. `heartbeat_only` keeps
  OD-11.
- [ ] **IF-0-CLOSEOUT-3 — Closeout ledger and roll-up.** These are metadata only, with no host
  names and no secrets in any encoding.
  - `plans/evidence/seat-closeout/exceptions.json`, schema `seat_exception_ledger.v1`. It has
    one entry per named matrix exception (Claude open egress, Codex unconfined, Grok
    unconfined) with `row`, `exception`, `expiry` (as the matrix states it), `end_condition`
    and `ended_by`. `ended_by.kind` is `phase_exit` or `expired_degraded`, with `ref` set to
    the landing PR or the degraded-resolution test. A renewed exception has not ended: it
    fails EC-CLOSEOUT-1, and SL-1 and SL-3 STOP and report it to the row's owner phase. It
    also holds one `removals` entry, for agent-harness#1480's `review`-seat fallback.
  - `plans/evidence/seat-closeout/rollup.json`, schema `seat_closeout_rollup.v1`. Each vendor,
    remote and president row has `status`, `live_evidence_digest`, the window record path and
    sha256, `owner_ec` and `interim_route`. Each host class has `capacity_offload: "disabled"`.
    It lists every carried-forward item with its check result, and the CLOSEOUT issue receipts
    as `{number, action, url}`.

## Lane Index & Dependencies

SL-1 — Seat sealed and unconfined removal (lane A)
  Depends on: (none)
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — President route removal (lane B)
  Depends on: SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Matrix, ledger, issues and docs reducer (lane C, SL-docs)
  Depends on: SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Seat sealed and unconfined removal (lane A)

- **Scope**: Under OD-8, make every `review`-seat route jailed, remote, native-fill or typed-degraded.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_preflight.py`, `phase-loop-runtime/tests/test_seats_closeout_seat_routes.py`, `phase-loop-runtime/tests/test_sealed_seat_never_counts.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_seat_jail.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `IF-0-CLOSEOUT-1`
- **Interfaces consumed**: `IF-0-JAILCORE-1` (pre-existing), `IF-0-JAILCORE-4` (pre-existing), `IF-0-FIRSTSEAT-3` (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.1 | test | — | Path-enter the broker spawn's seat-mode resolution and its launch through _default_spawn for each of the five legs, plus `opencode` and `cursor`, on a staged `review` tree with no profile, an expired exception, a stale pass and a host-capability miss. Assert that no mode is `unconfined` or `sealed`, that nothing launches on `degraded`, and that each code is in `NOTICES` with a fix line naming no removed route. Mutation: restore the `seat_filesystem_unconfined` branch and the test fails. Assert that the profile-digest fixtures, `_FD_CLOSER` and the `SDK_PROOF_REGIONS` names are unchanged. | `V1` |
| SL-1.2 | impl | SL-1.1 | Land IF-0-CLOSEOUT-1. `seat_jail.py` changes only `NOTICES` fix-line text, and only where a line names a removed route. | `V1`, `V3` |
| SL-1.3 | verify | SL-1.2 | Run the lane tests, the inventories and `audit-order`. | `V1`, `V3` |

### SL-2 — President route removal (lane B)

- **Scope**: Under OD-8, bring each president rung to a tooled route or a typed-degraded rung, and remove the sealed president commands.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/tests/test_seats_closeout_president.py`, `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_president_ladder_config.py`, `phase-loop-runtime/tests/president_fakes.py`
- **Interfaces provided**: `IF-0-CLOSEOUT-2`
- **Interfaces consumed**: `IF-0-CLOSEOUT-1`, `IF-0-JAILCORE-1` (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Enter through the governed board's president ladder with fake rungs and the board's staged tree. Cover each rung on each host class. A rung whose vendor resolves jailed launches with tools. A rung whose vendor row is `remote-pending` is typed-degraded, writes its start entry and the ladder advances. A silent `bounded` rung ends typed within its bound. No path reaches a sealed command. The inventory reports no `sealed` `tool_mode`. Mutation: restore the tools-off `_run_claude_print_session` president call, and the test fails. | `V2` |
| SL-2.2 | impl | SL-2.1 | Land IF-0-CLOSEOUT-2 and remove the sealed president commands. | `V2`, `V3` |
| SL-2.3 | verify | SL-2.2 | Run the lane tests, `test_president_heartbeat_1001.py`, the inventories and `audit-order`. | `V2`, `V3` |

### SL-3 — Matrix, ledger, issues and docs reducer (lane C, SL-docs)

- **Scope**: Settle the final readiness matrix and card, write the ledger and roll-up, close the owned issues, and update the docs and CHANGELOG.
- **Owned files**: `docs/review-seats-readiness.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-issue-index.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `plans/evidence/seat-closeout/exceptions.json`, `plans/evidence/seat-closeout/rollup.json`, `plans/evidence/seat-inventory/dispositions.json`, `plans/evidence/seat-inventory/index.json`, `phase-loop-runtime/tests/test_seats_closeout_ledger.py`, `specs/roadmap-status.json`, `specs/phase-plans-seats-v1.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `.doc-decisions.json`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-CLOSEOUT-3`
- **Interfaces consumed**: `IF-0-CLOSEOUT-1`, `IF-0-CLOSEOUT-2`, `IF-0-FIRSTSEAT-1` (pre-existing), `IF-0-FIRSTSEAT-2` (pre-existing); findings: each owner phase's window records, the OD-3b/OD-4/OD-5/OD-6 sections, OD-9 records, and the E1–E5 results

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | test | — | Write `test_seats_closeout_ledger.py`. Both files must match their schemas. Each exception entry's `ended_by` must resolve: a `phase_exit` ref is a merged PR, and `expired_degraded` names a passing degraded-resolution test. Each matrix row must equal its roll-up entry. Each `remote-pending` row must have a degraded interim route and an open REMOTE issue. Each host class must read `capacity_offload: "disabled"`, and packaged route policy must hold no grant. The card's seat and president tables must equal the matrix. Negative controls: a `candidate` row, an exception with no `ended_by`, an owner_renewal entry, an unrecorded carried-forward check, and a host name in any record. | `V5` |
| SL-3.2 | docs | SL-3.1 | Run E1–E5 and the carried-forward checks, and write `exceptions.json` and `rollup.json`. After the expiry the matrix states for it, an exception whose end condition is unmet is recorded `expired_degraded`. A renewed exception STOPs SL-3 under EC-CLOSEOUT-1. | `V5` |
| SL-3.3 | docs | SL-3.2, SL-2 | Settle the matrix under EC-CLOSEOUT-2 and EC-CLOSEOUT-4, with the president rows taken from IF-0-CLOSEOUT-2. A row still `candidate` waits for its row window. Update the card, CONTRACTS.md and the CHANGELOG. Rescan the docs catalog. | `V5`, `V4` |
| SL-3.4 | docs | SL-3.3 | Issue sweep. Close agent-harness#1132 and agent-harness#1288 citing the matrix. Comment the matrix on agent-harness#1244, which stays open for the per-OS jails. Close agent-harness#1250 citing SL-2. Sweep the unnamed index rows (Context). Record each CLOSEOUT issue receipt in the roll-up only. `dispositions.json` changes only through the four owner-closure moves required by E2. Mark each in the issue index. Screen every body under OD-10 and the INVENTORY pre-post check. | `VC` |
| SL-3.5 | docs | SL-3.4 | Only once REMOTE has exited, as checked by its ECs on main: move the registry entry and line 3 to `delivered` in one commit (EC-CLOSEOUT-3). Otherwise record the open REMOTE deferral and stop. The same commit re-pins `roadmap_sha256` in `index.json` and `dispositions.json` after changing roadmap line 3. | `V4` |
| SL-3.6 | verify | SL-3.5 | Run the docs, roadmap and ledger checks. | `V4`, `V5` |

## Execution Notes

- **Critical path.** E1–E5, then SL-1 → SL-2 as drafts, then OD-8, then merge, then SL-3.3
  onward. SL-2 starts from a base that contains SL-1. SL-3 depends on SL-1 and SL-2 from SL-3.3
  onward; SL-3.1-SL-3.2 may start earlier.
- **SL-2 named edits.** `panel_invoker.py` stays with SL-1 (check D). SL-2 may edit only the
  president launch sites in it, on a draft stacked on SL-1 before SL-1 merges (OD-8 still gates
  both merges): the tools-off `_run_claude_print_session`
  president call, the TUI president session, and the president's `_exec_leg` throwaway-directory
  use, plus passing the board's staged tree to the president route. If PANELSPLIT moved them,
  SL-2 edits the named successors and records the path.
- **Single writers.** `seat_jail.py`, `panel_invoker.py`, the readiness doc, the card and the
  CHANGELOG were last written by the vendor phases. CLOSEOUT runs after them and preserves their
  sections, and the later lander rebases. CLOSEOUT changes no profile, allowlist or qualification
  digest. A digest change belongs to the row's owner phase (principle 4).
- **Live work.** CLOSEOUT runs no window. A row that needs one rides the owner's next row window
  on the seat host (principle 5).
- **Owner decisions.** OD-8 gates the merge of SL-1 and SL-2, not their draft implementation or
  review.
  **OD-C1 (roadmap-level): RESOLVED** by owner ruling, recorded in the roadmap amendment that
  redefines `done-local`. `done-local` means qualified on the owner's designated standard host,
  with one operator. Team-host coverage is a separate later status that no CLOSEOUT check, entry
  check or EC requires. W1, each vendor row window, E1 and EC-CLOSEOUT-2 apply the amended rule.
  That amendment changes the roadmap's bytes, so this plan's `roadmap_sha256` is re-pinned when
  it merges. Until then, SL-3.3 settles no row.
- **Load limits.** Run the targeted files serially under `timeout 900`. The full suite runs on
  hosted CI only, and Gate A follows the sprint policy in force at landing.
- **Known destructive changes**: SL-1 and SL-2 remove the routes EC-CLOSEOUT-1 and
  EC-CLOSEOUT-4 name. Nothing else is deleted.
- **Expected conflicts**: union-resolve `CHANGELOG.md`, `plans/manifest.json` and
  `tests/data` inventories under the sprint rule.
- **Stale-base guidance.** A lane whose base predates its upstream lane MUST stop and report,
  never reset.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/advisor-board-capabilities-card.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- evidence paths: `docs/review-seats-readiness.md`, `plans/evidence/seat-closeout/exceptions.json`, `plans/evidence/seat-closeout/rollup.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-CLOSEOUT-1 — proven by `V1`, `V3` and `exceptions.json`, with E5 met and OD-8 recorded. Falsified by any `review`-seat path reaching `unconfined` or `sealed`, a restored `seat_filesystem_unconfined` branch that `V1` misses, an exception with no `phase_exit` or `expired_degraded` ending, an `owner_renewal` entry, or a changed profile digest. Path-entered control: the broker spawn's seat-mode resolution and `_default_spawn`, not a helper call.
- [ ] EC-CLOSEOUT-2 — proven by `V5`, `rollup.json` and the settled matrix, with OD-C1 resolved. Falsified by a `candidate` row, a `remote-pending` row with no degraded interim route or no open REMOTE issue, card-matrix drift, or a host class with capacity offload enabled. Path-entered control: `V5` reads the committed matrix and records, not fixtures.
- [ ] EC-CLOSEOUT-3 — proven by `VC` and the roll-up receipts. Falsified by agent-harness#1132 or agent-harness#1288 open, agent-harness#1244 with no matrix comment, an unnamed index row left unswept, a CLOSEOUT receipt written to `dispositions.json` `closures`, or the registry reading `delivered` before REMOTE has exited.
- [ ] EC-CLOSEOUT-4 — proven by `V2` and the president matrix rows. Falsified by a rung that is neither tooled nor typed-degraded, a reachable sealed president command, or a silent `bounded` rung that is not ended within its bound. Path-entered control: the governed board's president ladder.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, serial, with
system python3.14.4 and file paths under `phase-loop-runtime/tests/`. New test files do not
exist on this plan-only checkout, so these are pending selectors, not receipts.

- `V1`: `P test_seats_closeout_seat_routes.py test_sealed_seat_never_counts.py`, then `P test_panel_invoker.py -k seat_mode`
- `V2`: `P test_seats_closeout_president.py test_president_wiring.py test_president_ladder_config.py test_president_heartbeat_1001.py`
- `V3`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py test_seats_claude_sdk.py`, then `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.claude_seat_transport audit-order --repo . --base origin/main`
- `V4`: `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `V5`: `P test_seats_closeout_ledger.py`
- `VC`: for 1132, 1288 and 1250, `gh issue view <n> --repo Consiliency/agent-harness --json state --jq .state` prints `CLOSED`. For 1244 it prints `OPEN`, with a matrix comment receipt in `rollup.json`.
- Full suite: hosted CI only.
