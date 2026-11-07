---
phase_loop_plan_version: 1
phase: CLOSEOUT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 9dc889c61a8d682dde30af65bf1597c1dca9a0df094fac747194d3629939b16e
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seats_closeout_seat_routes.py", "phase-loop-runtime/tests/test_sealed_seat_never_counts.py", "phase-loop-runtime/tests/test_seats_closeout_president.py", "phase-loop-runtime/tests/test_president_wiring.py", "phase-loop-runtime/tests/test_president_ladder_config.py", "phase-loop-runtime/tests/test_president_heartbeat_1001.py", "phase-loop-runtime/tests/test_seats_closeout_ledger.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# CLOSEOUT: Local Closeout

## Context

This plan covers roadmap Phase 11 (CLOSEOUT) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Acceptance is EC-CLOSEOUT-1 to EC-CLOSEOUT-4, cited by ID only. Every other
SEATS phase plan is on main; this plan consumes their ECs and records, and restates none.

**Execution gate.** Plan now. Lanes SL-1 and SL-2 execute only after OD-8 is recorded and the
entry checks below pass on the lane's base tree. SL-3 may start its ledger and roll-up as soon
as this plan lands, but it settles no row before that row's owner phase has exited.

**Inputs.** The roadmap is pinned in the frontmatter, checked with `_sha256_file`. Every other
input is read by content on the lane's base tree, never pinned by digest here:
`plans/evidence/seat-inventory/index.json`, `plans/evidence/seat-inventory/dispositions.json`,
the TEAMHOST and caps contracts, the owner phases' decision records and window records. No lane
pins a SHA this phase will create.

**Owner rulings in force (2026-11-06).**

- One host class runs sandboxed review seats. The owner's private roster names the host. The
  shared developer host is being unloaded: it is not a seat host, and no CLOSEOUT live step,
  window or `VD` run takes place on it. The public text names host classes only (principle 8).
- Capacity offload ships disabled on every host. CLOSEOUT adds no `CapacityGrant` and no
  private host policy. The final matrix records "capacity offload: disabled" for each host
  class.
- Per-seat caps come before local enforcement. SL-1 removes the last unconfined route, which
  makes the jail the only local route, so SL-1 lands only after JAILCORE SL-5 is on main and
  its `VC` probe has passed (not skipped) on the seat host (entry check E3).

**Entry checks (by content, on the lane's base tree).**

- E1. Each of CLAUDENET, CODEX, GROK, PI and CLAUDETUI has exited, or its row is
  `remote-pending` under an OD-9 record (principle 6).
- E2. `dispositions.json` has an empty `pending_actions`. Its four rows at the input pin belong
  to EC-CLAUDE-2, EC-CLAUDE-3 and EC-CLAUDETUI-1. If any remain, STOP and report the row to its
  owner phase.
- E3. `seat_resource_caps.py` exists, the caps test passes, and the seat-host `VC` receipt is
  recorded (JAILCORE SL-5 host gate).
- E4. Every carried-forward item below is met in its owner's landing.

**Carried-forward items.** CLOSEOUT does not do the owner's work for these. It checks each one
in SL-3.1 and records the result in the roll-up. A miss STOPs SL-3 and is reported to the owner.

| Item | Owner | CLOSEOUT check |
|---|---|---|
| The "untrusted Grok surface" case in the `seats_teamhost_agreement` fixture table. agent-harness#1882 removed it from TEAMHOST. | GROK implementation, alongside its profile registration | The agreement test contains a Grok case whose surface is unverified, and that case does not report `present` |
| The Claude SDK launch fixture re-pin in the caps work | JAILCORE SL-5, caps contract §4 SDK worker row | SL-5's capped SDK worker test pins `launch-v1.json` at the digest that file has on the base tree. At the input pin that digest is `84c486a6…` |
| Live agy requalification after TEAMHOST SL-3 | TEAMHOST, in the next Gemini row window (principle 4, EC-TEAMHOST-7) | The Gemini row's window record carries the agy profile digest that `agy_profile_digest()` returns on the base tree |
| W0 | CLAUDE (LA-3), OD-3b | The W0 records exist under `plans/evidence/seat-qualification/claude-w0/`, and the OD-3b section cites them |
| W1 | FIRSTSEAT | The W1 record exists, and the Gemini row cites its digest |
| CLAUDETUI `VD` runs | CLAUDETUI SL-1.3 | `plans/evidence/seat-tui/startup-diagnosis.json` exists, and the OD-6 section cites its digest |
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
  `seat_jail.NOTICES`. `MODE_UNCONFINED` and `MODE_SEALED` stay in `seat_preflight.SEAT_MODES`
  only so stored records still parse. No `review` path can reach them. Advisory runs with no
  staged tree keep `seat_sandbox_not_staged`, which never counts as a review seat. The
  descend sets, `CAPACITY_CODES`, the profile builders and every profile digest stay
  byte-identical. No fix line names a removed route or an API-key lane.
- [ ] **IF-0-CLOSEOUT-2 — President rung routes.** `president_rung_inventory()` derives
  `tool_mode` for each rung from the same route resolver the review seats use: `tooled` when
  that resolver returns `jailed` or remote, and `degraded` with its code otherwise. The P-LR
  sealed last resort (agent-harness#1250) is removed. A degraded rung writes its start entry
  and a typed outcome, and the ladder advances (EC-FIRSTSEAT-2 bound unchanged).
  `heartbeat_only` keeps OD-11.
- [ ] **IF-0-CLOSEOUT-3 — Closeout ledger and roll-up.** These are metadata only, with no host
  names and no secrets in any encoding.
  - `plans/evidence/seat-closeout/exceptions.json`, schema `seat_exception_ledger.v1`. It has
    one entry per named matrix exception (Claude open egress, Codex unconfined, Grok
    unconfined) with `row`, `exception`, `expiry` (as the matrix states it), `end_condition`
    and `ended_by`. `ended_by.kind` is one of `phase_exit`, `expired_degraded` or
    `owner_renewal`, with `ref` set to the landing PR, the degraded-resolution test or the
    owner record. It also holds one `removals` entry, for agent-harness#1480's `review`-seat
    fallback.
  - `plans/evidence/seat-closeout/rollup.json`, schema `seat_closeout_rollup.v1`. Each vendor,
    remote and president row has `status`, `live_evidence_digest`, the window record path and
    sha256, `owner_ec` and `interim_route`. Each host class has `capacity_offload: "disabled"`.
    It lists every carried-forward item with its check result, and the issue receipts as
    `{number, action, url}`.

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
| SL-1.1 | test | — | Path-enter the broker spawn's seat-mode resolution for each of the five legs, plus `opencode` and `cursor`, on a staged `review` tree with no profile, an expired exception, a stale pass and a host-capability miss. Assert that no mode is `unconfined` or `sealed`, that nothing launches on `degraded`, and that each code is in `NOTICES` with a fix line naming no removed route. Mutation: restore the `seat_filesystem_unconfined` branch and the test fails. Assert that the profile-digest fixtures and `_FD_CLOSER` are unchanged. | `V1` |
| SL-1.2 | impl | SL-1.1 | Land IF-0-CLOSEOUT-1. `seat_jail.py` changes only `NOTICES` fix-line text, and only where a line names a removed route. | `V1`, `V3` |
| SL-1.3 | verify | SL-1.2 | Run the lane tests, the inventories and `audit-order`. | `V1`, `V3` |

### SL-2 — President route removal (lane B)

- **Scope**: Under OD-8, bring each president rung to a tooled route or a typed-degraded rung, and remove P-LR.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/tests/test_seats_closeout_president.py`, `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_president_ladder_config.py`, `phase-loop-runtime/tests/president_fakes.py`
- **Interfaces provided**: `IF-0-CLOSEOUT-2`
- **Interfaces consumed**: `IF-0-CLOSEOUT-1`, `IF-0-JAILCORE-1` (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Enter through the governed board's president ladder with fake rungs. Cover each rung on each host class. A rung whose vendor resolves jailed launches with tools. A rung whose vendor row is `remote-pending` is typed-degraded, writes its start entry and the ladder advances. A silent `bounded` rung ends typed within its bound. No path reaches a sealed command. The inventory reports no `sealed` `tool_mode`. Mutation: restore P-LR and the test fails. | `V2` |
| SL-2.2 | impl | SL-2.1 | Land IF-0-CLOSEOUT-2 and remove P-LR. | `V2`, `V3` |
| SL-2.3 | verify | SL-2.2 | Run the lane tests, `test_president_heartbeat_1001.py`, the inventories and `audit-order`. | `V2`, `V3` |

### SL-3 — Matrix, ledger, issues and docs reducer (lane C, SL-docs)

- **Scope**: Settle the final readiness matrix and card, write the ledger and roll-up, close the owned issues, and update the docs and CHANGELOG.
- **Owned files**: `docs/review-seats-readiness.md`, `docs/advisor-board-capabilities-card.md`, `docs/review-seats-issue-index.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `plans/evidence/seat-closeout/exceptions.json`, `plans/evidence/seat-closeout/rollup.json`, `plans/evidence/seat-inventory/dispositions.json`, `phase-loop-runtime/tests/test_seats_closeout_ledger.py`, `specs/roadmap-status.json`, `specs/phase-plans-seats-v1.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `.doc-decisions.json`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-CLOSEOUT-3`
- **Interfaces consumed**: `IF-0-CLOSEOUT-1`, `IF-0-CLOSEOUT-2`, `IF-0-FIRSTSEAT-1` (pre-existing), `IF-0-FIRSTSEAT-2` (pre-existing); findings: each owner phase's window records, the OD-3b/OD-4/OD-5/OD-6 sections, OD-9 records, and the E1–E4 results

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | test | — | Write `test_seats_closeout_ledger.py`. Both files must match their schemas. Each exception entry's `ended_by` must resolve: a `phase_exit` ref is a merged PR, `expired_degraded` names a passing degraded-resolution test, and `owner_renewal` is an owner record cited in the matrix. Each matrix row must equal its roll-up entry. Each `remote-pending` row must have a degraded interim route and an open REMOTE issue. Each host class must read `capacity_offload: "disabled"`, and packaged route policy must hold no grant. The card's seat and president tables must equal the matrix. Negative controls: a `candidate` row, an exception with no `ended_by`, an unrecorded carried-forward check, and a host name in any record. | `V5` |
| SL-3.2 | docs | SL-3.1 | Run E1–E4 and the carried-forward checks, and write `exceptions.json` and `rollup.json`. After 2026-12-04 UTC, an exception whose end condition is unmet is recorded `expired_degraded`. Only an owner record renews one. | `V5` |
| SL-3.3 | docs | SL-3.2, SL-2 | Settle the matrix under EC-CLOSEOUT-2 and EC-CLOSEOUT-4, with the president rows taken from IF-0-CLOSEOUT-2. A row still `candidate` waits for its row window. Update the card, CONTRACTS.md and the CHANGELOG. Rescan the docs catalog. | `V5`, `V4` |
| SL-3.4 | docs | SL-3.3 | Issue sweep. Close agent-harness#1132 and agent-harness#1288 citing the matrix. Comment the matrix on agent-harness#1244, which stays open for the per-OS jails. Close agent-harness#1250 citing SL-2. Sweep the unnamed index rows (Context). Record each receipt in `dispositions.json` `closures` and in the roll-up, and mark it in the issue index. Screen every body under OD-10 and the INVENTORY pre-post check. | `VC` |
| SL-3.5 | docs | SL-3.4 | Only once REMOTE has exited, as checked by its ECs on main: move the registry entry and line 3 to `delivered` in one commit (EC-CLOSEOUT-3). Otherwise record the open REMOTE deferral and stop. | `V4` |
| SL-3.6 | verify | SL-3.5 | Run the docs, roadmap and ledger checks. | `V4`, `V5` |

## Execution Notes

- **Critical path.** E1–E4, then OD-8, then SL-1 → SL-2 → SL-3. SL-2 starts from a base that
  contains SL-1. SL-3.1 and SL-3.2 may start earlier, but SL-3.3 waits for both lanes.
- **SL-2 named edits.** `panel_invoker.py` stays with SL-1 (check D). After SL-1 merges, SL-2
  may edit only the president launch sites that `president_adapter.py` calls (the
  `_run_claude_print_session` president use, and the brokered president session). If PANELSPLIT
  moved them, SL-2 edits the named successors and records the path.
- **Single writers.** `seat_jail.py`, `panel_invoker.py`, the readiness doc, the card and the
  CHANGELOG were last written by the vendor phases. CLOSEOUT runs after them and preserves their
  sections, and the later lander rebases. CLOSEOUT changes no profile, allowlist or qualification
  digest. A digest change belongs to the row's owner phase (principle 4).
- **Live work.** CLOSEOUT runs no window. A row that needs one rides the owner's next row window
  on the seat host (principle 5).
- **Owner decisions.** OD-8 gates SL-1 and SL-2. OD-C1 (below) gates SL-3.3's row settlement.
  **OD-C1:** principle 1 requires one standard host and one team host under two operator
  accounts. The current roster has one seat host class and one operator account. The owner
  either amends the roadmap's host-coverage rule or provisions the missing class or account
  (LA-1, LA-2). Until then, rows cannot reach `done-local`.
- **Load limits.** Run the targeted files serially under `timeout 900`. The full suite runs on
  hosted CI only, and Gate A follows the sprint policy in force at landing.
- **Known destructive changes**: SL-1 and SL-2 remove the routes EC-CLOSEOUT-1 and
  EC-CLOSEOUT-4 name. SL-3 moves dispositions rows into `closures`. Nothing else is deleted.
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

- [ ] EC-CLOSEOUT-1 — proven by `V1`, `V3` and `exceptions.json`, with OD-8 recorded. Falsified by any `review`-seat path reaching `unconfined` or `sealed`, a restored `seat_filesystem_unconfined` branch that `V1` misses, an exception with no resolved `ended_by`, or a changed profile digest. Path-entered control: the broker spawn's seat-mode resolution, not a helper call.
- [ ] EC-CLOSEOUT-2 — proven by `V5`, `rollup.json` and the settled matrix. Falsified by a `candidate` row, a `remote-pending` row with no degraded interim route or no open REMOTE issue, card-matrix drift, or a host class with capacity offload enabled. Path-entered control: `V5` reads the committed matrix and records, not fixtures.
- [ ] EC-CLOSEOUT-3 — proven by `VC` and the `dispositions.json` receipts. Falsified by agent-harness#1132 or agent-harness#1288 open, agent-harness#1244 with no matrix comment, an unnamed index row left unswept, or the registry reading `delivered` before REMOTE has exited.
- [ ] EC-CLOSEOUT-4 — proven by `V2` and the president matrix rows. Falsified by a rung that is neither tooled nor typed-degraded, a reachable P-LR, or a silent `bounded` rung that is not ended within its bound. Path-entered control: the governed board's president ladder.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, serial, with
system python3.14.4 and file paths under `phase-loop-runtime/tests/`. New test files do not
exist on this plan-only checkout, so these are pending selectors, not receipts.

- `V1`: `P test_seats_closeout_seat_routes.py test_sealed_seat_never_counts.py`, then `P test_panel_invoker.py -k seat_mode`
- `V2`: `P test_seats_closeout_president.py test_president_wiring.py test_president_ladder_config.py test_president_heartbeat_1001.py`
- `V3`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py`, then `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.claude_seat_transport audit-order --repo . --base origin/main`
- `V4`: `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `V5`: `P test_seats_closeout_ledger.py`
- `VC`: for 1132, 1288 and 1250, `gh issue view <n> --repo Consiliency/agent-harness --json state --jq .state` prints `CLOSED`. For 1244 it prints `OPEN`, with a matrix comment receipt in `dispositions.json`.
- Full suite: hosted CI only.
