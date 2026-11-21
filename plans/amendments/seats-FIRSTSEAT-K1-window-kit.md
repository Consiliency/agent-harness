---
phase_loop_plan_version: 1
phase: FIRSTSEAT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: b91c98ad7b9097ba411ca21f39cf390878dabac449e59d6fdfd1750915c16a09
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_seat_window_vendor_neutral.py", "phase-loop-runtime/tests/test_seat_window_supply_codex.py", "phase-loop-runtime/tests/test_seat_qualification_host_context.py", "phase-loop-runtime/tests/test_seat_jail_qualification_entry.py", "phase-loop-runtime/tests/test_seat_profile_codex.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_agy_qci.py"]
---

# FIRSTSEAT amendment K-1: one window kit for every vendor

## Context

This amends `plans/phase-plan-v1-seats-FIRSTSEAT.md` (roadmap Phase 0). Its lane E
(SL-4) delivered IF-0-FIRSTSEAT-2 for Gemini only, so EC-FIRSTSEAT-6 is not yet met for a
second vendor, and no Codex, Claude or Grok row window can run (principle 5). This
amendment adds the lanes that close that gap. It changes no roadmap text and no EC.

**Owner.** FIRSTSEAT owns the vendor-parametric window kit. The roadmap already gives it
IF-0-FIRSTSEAT-2 and EC-FIRSTSEAT-6, whose falsifier is a vendor needing its own procedure,
and FIRSTSEAT lane E owns `seat_window.py` and `cli.py`. Gemini's digests are also
FIRSTSEAT's (principle 4), so the one lane that refactors the Gemini path is under the
phase that owns them. JAILCORE SL-3.5 supplied the profile-sourced `WindowRows` seam only.
Vendor phases supply data and run their own windows. Contract §1 has the table.

**Why one owner and not a vendor phase.** If CODEX, CLAUDENET or GROK owned the kit, the
other two would wait on that phase's lanes, which is a window joining vendors in all but
name. A JAILCORE erratum would reopen a phase whose lanes have landed, for code that
JAILCORE's plan never scoped.

**Records-only amendments made with this plan.** These correct the plans that mis-assign
the kit. Each is a dated note, and none changes a lane's files or an EC:

- CODEX: the "Coordinator rulings" sentence now names FIRSTSEAT (this amendment) as the
  kit owner, and Interfaces consumed names the kit as extended here.
- JAILCORE: SL-3.5 and Interfaces provided record that SL-3.5 delivered the profile rows
  only.
- CLAUDENET: Interfaces consumed names the extended kit and this amendment's Claude lane.
  The "Open with JAILCORE (GROK plan S-2)" item is resolved in source, where
  `readiness_rows()` already drops `open egress` once the profile has an allowlist.
- GROK: S-2 is resolved in source in the same way. SL-2's jailed launch site calls the
  board-leg hook of contract §5.4.
- FIRSTSEAT: SL-4 has a dated ownership note pointing here.

**Design.** It is frozen in `plans/artifacts/seats-window-kit-k1-contract.md` (the
**contract**, sha256 `a284085cad9a72c036d3490d16cc5563c568d88e6e61017fcafc6cea77f8d4df`), which this plan cites and does not restate.
In summary:

- a supplier protocol and a closed supplier table (§4);
- the launch-control and board deltas to I-11, I-12 and I-15 (§5);
- reducer rules R1 to R8, so that only a vendor's own record can qualify that vendor's
  row (§6);
- `qualify --vendor` (§7) and live grants closed per vendor (§8);
- per-window launch caps (§9);
- per-vendor appendices, with Codex frozen and Claude and Grok tied to their phases'
  interfaces (§10);
- the pin table (§11), sequencing with W1 (§12) and falsifiers F1 to F12 (§13).

**Inputs** are the four digests pinned in contract §0. Nothing in this plan pins a commit.

**Skill.** `claude-plan-phase`, in amendment form (the `plans/amendments/` pattern). The
work has several lanes with disjoint files, interface freezes and content gates, and it
amends a pipeline phase. `claude-plan-detailed` covers one bounded change outside the
pipeline, so it does not fit.

## Interface Freeze Gates

- [ ] IF-0-FIRSTSEAT-6 — the K-1 kit interfaces: `WindowVendorData` v2 and its registration
  checks (contract §3), the supplier protocol and `seat_window_supply.SUPPLIERS` (§4), the
  `WindowLaunchSpec.leg`, `WindowBoardSpec.leg` and generic `WindowBoardResult` fields, and
  `window_board_for` (§5), reducer rules R1 to R8 (§6), the CLI (§7), `WINDOW_GRANTS` (§8)
  and the launch ledger (§9).

## Lane Index & Dependencies

SL-5 — K1-KIT: vendor-neutral kit, reducer, CLI and launcher
  Depends on: (none)
  Blocks: SL-6, SL-7, SL-8, SL-9
  Parallel-safe: no

SL-6 — K1-CODEX: Codex supplier adapter
  Depends on: SL-5
  Blocks: SL-9
  Parallel-safe: yes

SL-7 — K1-CLAUDE: Claude supplier adapter
  Depends on: SL-5
  Blocks: (none)
  Parallel-safe: yes

SL-8 — K1-GROK: Grok supplier adapter
  Depends on: SL-5
  Blocks: (none)
  Parallel-safe: yes

SL-9 — Documentation & spec reconciliation
  Depends on: SL-5, SL-6
  Blocks: (none)
  Parallel-safe: no

**Content gates** (checked on the lane's base tree, never by commit):

- **SL-5** starts when its base holds the W1 fixes and the W1-opening change, as contract
  §12 lists them. It merges after the W1 release has been cut, or earlier only as contract
  §12 allows.
- **SL-6** may be written against IF-0-FIRSTSEAT-6 while SL-5 is in review, and lands after
  it. Codex's row window becomes runnable when SL-5 and SL-6 are in an installed release.
- **SL-7** starts when its base holds IF-0-CLAUDENET-1 to IF-0-CLAUDENET-3 and the
  `claude-credential-scope` receipt (contract §10.C).
- **SL-8** starts when its base holds IF-0-GROK-1 and IF-0-GROK-2, with the jailed Grok
  launch site calling `window_board_for("grok", ...)`, and `probe-tools` passes on the
  measured surface (contract §10.D).

Order and rough size: SL-5 (large), then SL-6 (medium), SL-9 (small), then SL-7 (medium,
after CLAUDENET), then SL-8 (medium, after GROK's measured surface).

## Lanes

### SL-5 — K1-KIT: vendor-neutral kit, reducer, CLI and launcher

- **Scope**: Make the kit vendor-neutral on both sides of the frozen interface, with Gemini
  behaviour byte-identical, plus the Codex board-leg hook and the per-vendor grants.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_gemini.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_seat_window_vendor_neutral.py`, `phase-loop-runtime/tests/data/seat_window_gemini_k1_golden.json`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`
- **Interfaces provided**: IF-0-FIRSTSEAT-6
- **Interfaces consumed**: IF-0-FIRSTSEAT-2 (pre-existing), I-11, I-12 and I-15 (pre-existing), `WindowRows` from IF-0-JAILCORE-1 (pre-existing), `jail_profile_digest` (pre-existing), `allowlist_ref` (pre-existing), the W1 fixes and the W1-opening change (pre-existing on the base, contract §12)
- **Parallel-safe**: no
- **Named parts.** `seat_profiles.py`: `WindowVendorData`, `register_window_data` and
  `GEMINI_WINDOW_DATA` only. `panel_invoker.py`: the window section of contract §1, plus
  the `window_board=` parameter and its three calls in `_exec_jailed_codex_leg`, and the
  argument in `_parent_infer`'s Codex branch. `test_panel_invoker.py`: the
  `seats_firstseat_exec_record_window_*` tests, edited only for the renamed result fields.
  The two inventories take entries for this lane's sites, entry by entry.
- **Stop rules.** Stop and report if the Gemini golden cannot be kept byte-identical; if any
  lane change touches `seat_jail_qualification.py`, `agy_qualification.py`, `gemini_heartbeat.py`,
  `panel_invoker.terminal_verdict` or the prompt and stream helpers it reaches;
  if `tests/test_agy_qci.py` or `tests/data/seat_profile_digests_jailcore.json` would
  change; or if a seat-jail builder, filter or allowlist file would change.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | (none) | `tests/data/seat_window_gemini_k1_golden.json` | the golden | `pytest tests/test_seat_window_vendor_neutral.py -k golden` |
| SL-5.2 | test | SL-5.1 | `tests/test_seat_window_vendor_neutral.py` | F1–F12 (contract §13), using a synthetic second vendor registered in a fixture | `pytest tests/test_seat_window_vendor_neutral.py` |
| SL-5.3 | impl | SL-5.2 | `seat_profiles.py`, `seat_window_supply.py`, `seat_window_supply_gemini.py`, `seat_window.py` | (none) | `pytest tests/test_seat_window_vendor_neutral.py tests/test_seat_qualification_host_context.py` |
| SL-5.4 | impl | SL-5.3 | `panel_invoker.py`, `tests/test_panel_invoker.py`, inventories | (none) | `pytest tests/test_panel_invoker.py -k "window or codex" tests/test_seat_window_vendor_neutral.py` |
| SL-5.5 | verify | SL-5.4 | all lane files | all | the frontmatter `suite_command` without the SL-6 file, `tests/test_agy_qci.py`, `tests/test_seat_launch_helpers_trusted.py` and `tests/test_seat_profiles.py` |

### SL-6 — K1-CODEX: Codex supplier adapter

- **Scope**: Implement contract §10.B as `seat_window_supply_codex.py`, which registers
  Codex's `WindowVendorData`, so that `qualify --window row --vendor codex` runs end to end
  offline against fixtures.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_codex.py`, `phase-loop-runtime/tests/test_seat_window_supply_codex.py`
- **Interfaces provided**: the Codex window supplier
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), IF-0-CODEX-1 to IF-0-CODEX-5 (pre-existing), `seat_jail_qualification` shared primitives (pre-existing)
- **Parallel-safe**: yes
- **Stop rules.** Stop if the adapter needs an edit to any CODEX-owned file
  (`seat_profile_codex.py`, `seat_codex_*.py`, `codex-allowlist.json`), if Codex's profile
  digest or allowlist digest would change, or if the Codex CLI's help or JSON stream cannot
  yield contract §10.B's facts without a new launch kind.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | (none) | `tests/test_seat_window_supply_codex.py` | registration; launch kinds and argv per kind; stream facts; scope, expired-copy and refresh outcomes; the fixture context end to end through `seat_window.qualify` with launchers stubbed at `window_control_launch`; F2, F3 and F9 with real Codex data | `pytest tests/test_seat_window_supply_codex.py` |
| SL-6.2 | impl | SL-6.1 | `seat_window_supply_codex.py` | (none) | `pytest tests/test_seat_window_supply_codex.py tests/test_seat_profile_codex.py` |
| SL-6.3 | verify | SL-6.2 | lane files | all | the frontmatter `suite_command` |

### SL-7 — K1-CLAUDE: Claude supplier adapter

- **Scope**: Implement contract §10.C as `seat_window_supply_claude.py`, plus the
  `window_board_for("claude", ...)` call at the jailed transport launch.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_claude.py`, `phase-loop-runtime/tests/test_seat_window_supply_claude.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_seat_transport.py`
- **Interfaces provided**: the Claude window supplier
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), IF-0-CLAUDENET-1 to IF-0-CLAUDENET-3 (content gate), IF-0-CLAUDE-1 (pre-existing), OD-3b's default (pre-existing on the base)
- **Parallel-safe**: yes
- **Named part.** `claude_seat_transport.py`: the hook call only, for the default
  transport. The lane runs the jailed Claude transport's `audit-order` check.
- **Stop rules.** Stop if the hook needs any other edit to `claude_seat_transport.py`, or any
  edit to `claude_seat_sdk.py`, the SDK worker contract or its receipt verifier; if Claude's
  profile digest would change; or if OD-3b has not recorded a default.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-7.1 | test | (none) | `tests/test_seat_window_supply_claude.py` | as SL-6.1 for Claude, plus a transport other than the default refused, and the hook reached only for the Claude window | `pytest tests/test_seat_window_supply_claude.py` |
| SL-7.2 | impl | SL-7.1 | adapter, transport hook | (none) | `pytest tests/test_seat_window_supply_claude.py tests/test_seat_profile_claude_egress.py` |
| SL-7.3 | verify | SL-7.2 | lane files | all | the frontmatter `suite_command`, `tests/test_seat_window_supply_claude.py` and `audit-order` |

### SL-8 — K1-GROK: Grok supplier adapter

- **Scope**: Implement contract §10.D as `seat_window_supply_grok.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_grok.py`, `phase-loop-runtime/tests/test_seat_window_supply_grok.py`
- **Interfaces provided**: the Grok window supplier
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), IF-0-GROK-1 and IF-0-GROK-2 (content gate), `probe_grok_tools` (pre-existing)
- **Parallel-safe**: yes
- **Stop rules.** Stop if the jailed Grok launch site lacks the hook call (GROK adds it), if a
  window launch cannot run without the route's retry, or if Grok's profile digest would
  change.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | (none) | `tests/test_seat_window_supply_grok.py` | as SL-6.1 for Grok, plus a window launch with an unmeasured tool surface refused before the board | `pytest tests/test_seat_window_supply_grok.py` |
| SL-8.2 | impl | SL-8.1 | adapter | (none) | `pytest tests/test_seat_window_supply_grok.py tests/test_grok_tool_surface.py` |
| SL-8.3 | verify | SL-8.2 | lane files | all | the frontmatter `suite_command` and `tests/test_seat_window_supply_grok.py` |

### SL-9 — Documentation & spec reconciliation

- **Scope**: Document the vendor-neutral kit and the Codex row window. Record SL-7 and SL-8
  as pending their content gates. Update the plan manifest.
- **Owned files**: `plans/evidence/seat-qualification/README.md`, `docs/review-seats-readiness.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `plans/manifest.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), the Codex window supplier (SL-6)
- **Parallel-safe**: no
- **Notes**: The kit text, the per-vendor commands and files, the launch caps and the grant
  rule. Readiness rows change only in their kit sentences, and no row's status changes.
  SL-7 and SL-8 make no docs change and are not producers for this lane: their vendor
  phase's records PR states the adapter's landing, so this reducer does not wait for them.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-9.1 | test | (none) | (none) | (none) | `pytest tests/test_seat_reference_inventory.py phase-loop-runtime/tests/test_legible_roadmap_contract.py` |
| SL-9.2 | docs | SL-9.1 | lane files | (none) | `python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/amendments/seats-FIRSTSEAT-K1-window-kit.md` |

## What each vendor phase still adds once K-1 lands

| Phase | Code | Live and records |
|---|---|---|
| CODEX | Nothing. | An owner-approved grant change for `("codex", "row")` (contract §8), landed by the kit owner. A release carrying SL-5 and SL-6 installed on the designated host, with the EC-EXECFIND-2 pass for the current Codex profile digest. LA-2 logins for all four board vendors under the operator account. LA-3 runs `qualify --window row --vendor codex`. A reviewed records PR adds the export and the Codex readiness row (CODEX SL-docs.3, EC-CODEX-4). |
| CLAUDENET | SL-2 sets `window=CLAUDE_WINDOW_ROWS` (IF-0-CLAUDENET-1, already planned). SL-3 exports the scope-measurement and refresh-detection functions behind its receipts, for the adapter to call. | After SL-7: the grant, release, LA-2, LA-3 and the records PR (SL-docs.3, EC-CLAUDENET-4). |
| GROK | SL-2's jailed launch site calls `window_board_for("grok", ...)` (contract §5.4) and registers the profile with its window rows. The measured surface. | After SL-8: the grant, release, LA-2, LA-3 and the records PR (EC-GROK-4). |
| PI | Blocked on a contract revision for board composition (contract §10.E). | — |

## Verification

Per lane, the commands in its table. Whole amendment: the frontmatter `suite_command`.
Each code PR also runs the launch and inventory checks (`tests/test_agent_cli_scratch_inventory_1147.py`,
`tests/test_seat_launch_helpers_trusted.py`, `tests/test_seat_reference_inventory.py` and a
Gate A-shaped tree from an installed wheel). SL-7 runs `audit-order`. Shared-host rule: the
listed files only, serially without `-n`, under `timeout`, after the headroom check; never a
full suite. No lane makes a live provider call, launches a seat or runs anything on a seat
host. The live row windows are owner actions (LA-3) outside this plan.

## Execution Notes

- **One PR per lane.** SL-5 lands first. SL-6 and SL-9 follow, and Codex becomes runnable
  when both are released and installed. SL-7 and SL-8 land when their content gates open.
  They may land after FIRSTSEAT exits; they stay this amendment's lanes under the kit owner
  (open question O-3).
- **Single-writer files.** `panel_invoker.py`, `seat_profiles.py` and
  `test_panel_invoker.py` are shared with TEAMHOST, CODEX, GROK, PI, CLAUDENET and v11
  PANELSPLIT. In this amendment only SL-5 writes them, in its named parts. Whichever lands
  second rebases. If PANELSPLIT has moved the window section, SL-5 edits the successor and
  records the path. `claude_seat_transport.py`: SL-7's named part only.
- **In-flight work.** SL-5's base must hold the W1 fixes and the W1-opening change
  (contract §12). The W0 two-session change edits `claude_bakeoff.py` and the CLAUDE plan,
  which no lane here touches.
- **Requalification.** None, by contract §11: no profile, allowlist, containment-contract,
  Gemini-binding, agy-QCI, EC-EXECFIND-2 or Claude-SDK input moves. Only `runtime_digest`
  moves, and it is recorded, not compared. A completed W1 stays valid, and the Gemini golden
  (F10) proves it.
- **Launch caps** for the owner's window packet: contract §9.2.
- **Open questions** (coordinator or owner):
  - O-1: R6 narrows when an expired exception invalidates a record. This is an owner
    decision, because it also lets W1 verify after 2026-12-04.
  - O-2: whether a per-vendor grant must also bind the host and the attempt, beyond a
    cutoff.
  - O-3: SL-7 and SL-8 staying under FIRSTSEAT after its exit.
  - O-4: the Claude hook's place in `claude_seat_transport.py`.
  - O-5: Pi's board composition.
- **Stall rule.** This is FIRSTSEAT's amendment for K-1. A second K-1 amendment, or one
  that edits a frozen contract, stops for a diagnosis (principle 6).
- **Known destructive changes**: `WindowBoardResult.canonical_gemini` and `.gemini` are
  removed (contract §5.3). Every reader is in SL-5's files.
- **Rollback.** Revert the lane. The W1 records and the golden are unaffected.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`.

- [ ] EC-FIRSTSEAT-6 — one kit, one record per vendor: proven by `pytest tests/test_seat_window_vendor_neutral.py` (F1–F9, F11, F12) through `seat_window.qualify`, `verify_records`, `reduce_readiness`, `export_records` and `cli_main`, with a fixture vendor registered only through `register_window_data`; falsified by a passing record of one vendor changing any row other than its own, by a failing vendor blocking another vendor's row, by a vendor needing a kit-code branch, or by a grant for one vendor opening another. Path-entered control: `cli_main` with `--vendor`, reading real retained source files from a 0700 fixture directory.
- [ ] EC-FIRSTSEAT-6 — Codex runs the same command: proven by `pytest tests/test_seat_window_supply_codex.py`, whose fixture context runs `qualify --window row --vendor codex` to a record that `verify --vendor codex` passes and that changes only `vendor:codex`; falsified by a Codex record carrying Gemini's profile, allowlist or contract digest passing, or by a window launch that retries. Path-entered control: `seat_window.run_native_window` with the production Codex supplier and launchers stubbed only at `window_control_launch` and `window_board_launch`.
- [ ] EC-FIRSTSEAT-7 — W1 evidence is kept: proven by `pytest tests/test_seat_window_vendor_neutral.py -k golden`, in which a W1 record set made by the pre-K-1 producer verifies, reduces and exports to the golden bytes, and `tests/test_agy_qci.py` and the profile-digest receipt are unchanged; falsified by any golden byte, Gemini argv or binding digest differing. Path-entered control: the real Gemini window data and its `seat_window_supply_gemini` supplier over the unedited `seat_jail_qualification`.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `plans/phase-plan-v1-seats-FIRSTSEAT.md`, `plans/phase-plan-v1-seats-CODEX.md`, `plans/phase-plan-v1-seats-JAILCORE.md`, `plans/phase-plan-v1-seats-CLAUDENET.md`, `plans/phase-plan-v1-seats-GROK.md`, `plans/evidence/seat-qualification/README.md`, `docs/review-seats-readiness.md`
- evidence paths: `phase-loop-runtime/tests/test_seat_window_vendor_neutral.py`, `phase-loop-runtime/tests/data/seat_window_gemini_k1_golden.json`
- redaction posture: `metadata_only`
- downstream handling: none; the roadmap is unchanged, and the plan amendments listed in Context land with this plan
