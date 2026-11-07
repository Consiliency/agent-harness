---
phase_loop_plan_version: 1
phase: CLAUDETUI
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 33f3f073db869be2349cce35a6f7bd86f1280b3f713c8c6f8a4dfa43d4aa8cbd
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_claude_tui_terminal.py", "phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py", "phase-loop-runtime/tests/test_panel_tui_liveness_188.py", "phase-loop-runtime/tests/test_panel_tui_eof_48.py", "phase-loop-runtime/tests/test_seat_notices.py", "phase-loop-runtime/tests/test_claude_tui_gate.py", "phase-loop-runtime/tests/test_seats_claude_transport.py", "phase-loop-runtime/tests/test_claude_transport_seam.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py"]
---

# CLAUDETUI: Claude TUI as Last Fallback

## Context

This plan covers roadmap Phase 9 (CLAUDETUI) of `specs/phase-plans-seats-v1.md`, tracked by
agent-harness#1820. Acceptance is EC-CLAUDETUI-1 and EC-CLAUDETUI-2, cited by ID only.

**Execution gate.** Plan now; execute after CLAUDE exits (roadmap Governance). The check is by
content: the base tree's decision record holds an OD-3b section, matched by the
`claude_seat_transport` `default` section pattern. Without it, every lane stops and reports.

**What is already on main.** Each part of the two salvaged drafts was checked against main.

| Source | Part | State on main | This phase |
|---|---|---|---|
| agent-harness#1641 | Native-image resolver | Landed (`_resolve_claude_executable`) | Cite |
| agent-harness#1641 | Private startup evidence | Absent: `_exec_jailed_claude_leg` replaces an unknown failure and drops its tail | SL-1 |
| agent-harness#1623 | Controlling terminal | Absent | SL-1, relocated |
| agent-harness#1623 | Startup-banner readiness | Absent from `modal_ignore` | SL-1 |
| agent-harness#1623 | Grok allow-list | Superseded by agent-harness#1652 | Cite |
| agent-harness#1623 | Resolver readability | Landed (agent-harness#1835) | Cite |
| agent-harness#1623 | Read-only preamble and inline-frame wording | Absent; part of the Grok change, not in the disposition table | Name in the closure comment |

**Why the terminal fix moves.** agent-harness#1623 edited `seat_jail._FD_CLOSER`.
`_profile_digest_of` hashes that string into every leg's digest, so that hunk would change
every seat's digest. Principle 4 and EC-CLAUDENET-2 forbid this here. `panel_invoker` already
has `_seat_fd_closer(keep, terminal_fd)`, which attaches a terminal. SL-1 applies it to the
jailed TUI command alone. `seat_jail.py`, a roadmap key file, therefore stays untouched.

**Diagnosis.** The cause of agent-harness#1461 is not established. agent-harness#1641 reached
the ready UI and then stalled. agent-harness#1623 reported a real TUI verdict with its fixes.
Neither is admissible evidence for this phase. The first retained record comes from `VD`, a
developer-host run after the salvage. It qualifies nothing and is not a window (principle 5).

**Settlement.** EC-CLAUDETUI-1 is unconditional, so the fixes land and both drafts close on
either OD-6 outcome. In both outcomes the jailed `tui` leaves this phase typed-degraded. The
outcomes differ only in whether a window can later admit it.

## Interface Freeze Gates

- [ ] **IF-0-CLAUDETUI-1 — jailed terminal step.** The jailed branch of
  `_run_claude_tui_session` launches `[*_seat_fd_closer(keep, 0), *command]`. `keep` holds the
  jail's token descriptor when present. A terminal held by another session refuses before the
  provider starts. `seat_jail._FD_CLOSER` stays byte-identical: input pin sha256
  `cdc19d98a72b7e7617ea26d843b325d6e17412d68d0ea0deac93a0756b799d91`. `command` and the exec
  record stay the provider's own.
- [ ] **IF-0-CLAUDETUI-2 — transport gate.** `claude_seat_transport` adds:
  - `JAILED_TUI_STATE: Literal["pending_window", "retired", "admitted"]`, a source literal read
    like `JAILED_CLAUDE_DEFAULT`.
  - `JAILED_TUI_AUTHORITY: RecordCitation`, citing the OD-6 section.
  - `tui_window_scope()`, a process-wide, lock-guarded context manager. No environment value
    opens it. `seat_window` wraps `window_board_launch` in it.
  - `resolve_jailed_claude_transport` refuses a selected or default `tui` with
    `claude_tui_degraded` when the state is `retired`, or `pending_window` outside the scope.
    Nothing launches.
  - `admitted` requires a window-record citation; a PR after this phase sets it.
  - `CODES` gains `claude_tui_degraded`, class `ordinary`. Its fix line names the recorded
    default and no key-based route. `is_admitted("tui")`, the default constants, capture and
    research seats, and brokered and president TUI routes do not change.
- [ ] **IF-0-CLAUDETUI-3 — diagnosis record and OD-6 rule.**
  `plans/evidence/seat-tui/startup-diagnosis.json`, schema `seat_tui_startup_diagnosis.v1`,
  holds `runtime_head`, `host_class`, `runs` (at most 3), each run's marker, `cause_class`,
  `bounded_fix` and `private_evidence_sha256[]`. `bounded_fix` is true only when an offline reproducer fails on the unmodified SL-1 base, passes with the candidate, and the fix stays in `panel_invoker.py`'s TUI session code with no added bind, environment, tool, descriptor or credential path and no digest change. True means `pending_window`. False means `retired`. Unknown after 3 runs is false.

## Lane Index & Dependencies

SL-1 — Diagnosis and repair (lane A)
  Depends on: (none)
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Degraded path and notice (lane B)
  Depends on: SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation, closures and matrix reducer (SL-docs)
  Depends on: SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-1 — Diagnosis and repair (lane A)

- **Scope**: Salvage the startup evidence, terminal and banner fixes, then diagnose agent-harness#1461, apply OD-6's rule and record it.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_claude_tui_terminal.py`, `phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/test_seat_notices.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/evidence/seat-tui/startup-diagnosis.json`, `plans/decision-claude-print-subscription-route-20261008.md`
- **Interfaces provided**: `IF-0-CLAUDETUI-1`, `IF-0-CLAUDETUI-3`, `OD-6 record section`, `claude_tui_degraded`
- **Interfaces consumed**: `IF-0-CLAUDE-1` (pre-existing), `OD-3b section` (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-1.1 | test | — | Path-enter `_exec_jailed_claude_leg` and `_run_claude_tui_session`. Prove: the jailed launch carries the terminal step; only a supplied terminal attaches; another session's terminal refuses before the provider; the token descriptor survives; the `_FD_CLOSER` sha holds. The banner cases (flag, env, settings) do not arm the editor. An unknown tail reaches the private leg log, a token tail does not, and the public detail stays the marker. | `V1` |
| SL-1.2 | impl | SL-1.1 | Land IF-0-CLAUDETUI-1. Port the banner check and the `_LegFailure` prefix retention onto main. Add the `claude_tui_degraded` literal to the closed detail list. | `V1`, `VL`, `V3` |
| SL-1.3 | evidence | SL-1.2 | Run `VD` at most three times on the branch head. Keep raw evidence private and retain only the schema's metadata for the final diagnosis record. Select a candidate cause and outcome, but do not set `bounded_fix=true` yet. A containment cause stops the lane and goes to the owner privately (OD-10); the public record later says `withheld_private` and nothing else. | `VD` |
| SL-1.4 | test | SL-1.3 | On a proposed repair outcome, identify the SL-1.1 red/green test that reproduces the diagnosed cause or add an offline reproducer that fails before the candidate fix. If no bounded offline reproducer exists after the capped diagnosis, select `retired`. | `V1` |
| SL-1.5 | impl | SL-1.4 | Repair branch only: apply the repair inside the IF-0-CLAUDETUI-3 bound and make the diagnosis reproducer pass. Retired branch: make no repair. | `V1`, `V3` |
| SL-1.6 | evidence/docs | SL-1.3; repair branch: SL-1.5 | Finalize the diagnosis record. Set `bounded_fix=true` only after the red/green reproduction and bound checks pass; otherwise set it false, including an unknown cause after three runs. Append a decision-record section whose heading names OD-6 and not OD-3b; it states the outcome, cites the diagnosis digest, and amends §4a item 3 for the jailed `tui`. | `V1`, `V3`, `VD` |

### SL-2 — Degraded path and notice (lane B)

- **Scope**: Make the jailed `tui` refuse with a typed notice unless a window scope or an admission opens it.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/tests/test_claude_tui_gate.py`, `phase-loop-runtime/tests/test_seats_claude_transport.py`
- **Interfaces provided**: `IF-0-CLAUDETUI-2`
- **Interfaces consumed**: `OD-6 record section`, `claude_tui_degraded`, `RecordCitation` (pre-existing), `_runtime_literal_facts` (pre-existing)

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-2.1 | test | — | Enter through `resolve_jailed_claude_transport` as the broker spawn calls it. Cover each state, selected and default `tui`, inside and outside the scope, an environment that tries to open it, and `admitted` with no citation. Assert nothing launches, the seat mode republishes degraded, and the citation's section bytes match the base record. Through `_exec_jailed_claude_leg`, a fake CLI ending its turn with no canonical output never returns OK. Prove `print` and `sdk` selection are unchanged. | `V2` |
| SL-2.2 | impl | SL-2.1 | Land IF-0-CLAUDETUI-2 with the state SL-1 recorded, and wrap `window_board_launch`. | `V2`, `V3` |
| SL-2.3 | verify | SL-2.2 | Run lane tests, inventories and `audit-order`. | `V2`, `V3` |

### SL-3 — Documentation, closures and matrix reducer (SL-docs)

- **Scope**: Settle the card, matrix and index, close both drafts, and record the receipts.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `docs/review-seats-readiness.md`, `docs/review-seats-issue-index.md`, `plans/evidence/seat-inventory/dispositions.json`, `CHANGELOG.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: `IF-0-CLAUDETUI-1`, `IF-0-CLAUDETUI-2`, `IF-0-CLAUDETUI-3`

| Task | Type | Depends on | Action | Proof |
|---|---|---|---|---|
| SL-3.1 | docs | SL-2 | Update the card's jailed-transport section and the changelog. Record the `tui` state beside the Claude row without changing that row's status. | `V4` |
| SL-3.2 | docs | SL-3.1 | Close agent-harness#1641 and agent-harness#1623 with comments citing the carrying PRs (SL-1, agent-harness#1652, agent-harness#1835 as each applies). The agent-harness#1623 comment also says its read-only preamble and inline-frame wording were not carried. Screen each body under OD-10 and the INVENTORY pre-post check. | `VC` |
| SL-3.3 | docs | SL-3.2 | Move both rows from `pending_actions` to `closures` with their `owner_receipt_url`, and mark them closed in the issue index. | `VC` |
| SL-3.4 | docs | SL-3.3 | Comment the diagnosis on agent-harness#1461, metadata only. Retired: close it citing the OD-6 section. `pending_window`: it stays open until a window admits `tui`. Comment on agent-harness#1639 that its source hunk did not land. | `VC` |
| SL-3.5 | verify | SL-3.4 | Run the docs and roadmap checks. | `V4` |

## Execution Notes

- **Critical path.** SL-1 → SL-2 → SL-3. SL-2 starts only from a base whose tree contains
  SL-1's OD-6 section. This keeps the record and the gate apart, as EC-CLAUDE-4 does by
  content.
- **OD-6.** Defaulted. An owner objection during SL-1's review overrides the IF-0-CLAUDETUI-3
  rule.
- **`tui` as default.** If OD-3b recorded that no transport was admitted, the default stays
  `tui` and SL-2 makes it refuse. OQ-7 names OD-6 as that end. `JAILED_CLAUDE_DEFAULT` does not
  change. No outcome of another transport launches `tui`.
- **Live check.** After exit in the repaired outcome, the next row window selects `tui` inside
  `tui_window_scope`. No window waits for it. `seat_window.readiness_rows` hard-codes
  `claude_transport: "print"`, so that window's PR makes the field follow the transport. Its PR
  sets `admitted`, records the matrix result and closes agent-harness#1461.
- **Open with CLAUDENET.** EC-CLAUDENET-1 reads `tui` only in the repaired outcome. Any new
  allowlist row is an amendment there, batched with its window. `VD` measures no allowlist.
- **Single writers.** `panel_invoker.py` is shared with JAILCORE SL-3, TEAMHOST SL-4/SL-8,
  CLAUDENET SL-2, CODEX, GROK, PI, FIRSTSEAT and v11 PANELSPLIT; `seat_window.py` is shared
  with JAILCORE SL-3.5. `docs/advisor-board-capabilities-card.md`,
  `docs/review-seats-readiness.md` and `CHANGELOG.md` are shared with JAILCORE SL-4,
  TEAMHOST SL-6 and CLAUDENET SL-4. The later lander rebases. CLAUDETUI edits only the TUI
  session and leg sites in `panel_invoker.py`, the TUI scope around `window_board_launch` in
  `seat_window.py`, its own Claude TUI state text in shared docs, and its own changelog and
  inventory entries; it preserves every other landed section. It does not edit
  `seat_jail.py`, profile fields or profile-digest data, so CLAUDENET retains the sole Claude
  digest change. If PANELSPLIT moved the code, SL-1 edits the named successor and records the
  path. SL-1's `seat_launch_references.json` edit is the only launch-reference inventory
  change.
- **Known destructive changes**: none. SL-3 moves the two owner-closure rows from
  `pending_actions` to `closures` while preserving their comment receipts; the remaining
  changes are additive or explicit state updates.
- **Expected conflicts**: rebase and preserve the named shared-file sections above.
  Union-resolve `CHANGELOG.md` under the sprint rule.
- **Stale-base guidance.** Lane teammates working in isolated worktrees do not see sibling-lane
  merges automatically. If a lane finds its worktree base is pre-SL-1, it MUST stop and report
  rather than committing. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale
  worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/advisor-board-capabilities-card.md`, `plans/decision-claude-print-subscription-route-20261008.md`
- evidence paths: `plans/evidence/seat-tui/startup-diagnosis.json`, `plans/evidence/seat-inventory/dispositions.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-CLAUDETUI-1 — proven by `V1`, `VL`, `VD` (the digests in `plans/evidence/seat-tui/startup-diagnosis.json`) and `VC`. Falsified by a jailed launch with no terminal step, a changed `_FD_CLOSER` sha, a banner line arming the editor, a dropped unknown tail, a retained token tail, or either draft open or unreceipted. Path-entered control: launches enter through `_exec_jailed_claude_leg`, not a direct helper call.
- [ ] EC-CLAUDETUI-2 — proven by `V2`, the OD-6 section and `V4`. Falsified by a provider launch from a refused state, an environment value opening the scope, a jailed `tui` run returning OK without canonical output, or a state that disagrees with the OD-6 section. Path-entered control: selection enters through `resolve_jailed_claude_transport`; output through `_exec_jailed_claude_leg` with a fake CLI.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, serial, with
system python3.14.4 and file paths under `phase-loop-runtime/tests/`. New test files are absent
on this plan-only checkout, so these are pending selectors, not receipts.

- `V1`: `P test_claude_tui_terminal.py test_panel_tui_workspace_trust_223.py test_panel_tui_liveness_188.py test_panel_tui_eof_48.py test_seat_notices.py`, then `P test_panel_invoker.py -k claude`
- `V2`: `P test_claude_tui_gate.py test_seats_claude_transport.py test_claude_transport_seam.py`, then `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.claude_seat_transport audit-order --repo . --base origin/main`
- `V3`: `P test_agent_cli_scratch_inventory_1147.py test_seat_launch_helpers_trusted.py test_seat_reference_inventory.py test_python_floor_1546.py`
- `V4`: `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-seats-v1.md`
- `VL`: `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 P test_claude_tui_terminal.py -k live_jail --junitxml=<private-receipt>`, provider-free, on a jail-capable host. A skip or zero collection fails.
- `VD`: a jailed Claude seat with `PHASE_LOOP_PANEL_CLAUDE_ROUTE=tui` on the real board path, on a developer host with a recorded jail pass and the developer's own login. Run from the branch head, on the operator's private storage. Not a window.
- `VC`: `gh pr view <n> --repo Consiliency/agent-harness --json state --jq .state` prints `CLOSED` for 1641 and 1623. `dispositions.json` then lists both under `closures` with `owner_ec` EC-CLAUDETUI-1 and neither under `pending_actions`.
- Full suite: hosted CI only. Gate A follows the sprint policy in force at landing.
