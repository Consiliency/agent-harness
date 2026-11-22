---
phase_loop_plan_version: 1
phase: FIRSTSEAT
roadmap: specs/phase-plans-seats-v1.md
roadmap_sha256: 2f26635bfcb5119967735cf5d5966f1ce39695a8331d2543eb9e11c07d187018
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q tests/test_seat_window_vendor_neutral.py tests/test_seat_window_grants.py tests/test_seat_window_supply_codex.py tests/test_seat_qualification_host_context.py tests/test_seat_jail_qualification_entry.py tests/test_seat_profile_codex.py tests/test_seat_reference_inventory.py tests/test_agy_qci.py"]
---

# FIRSTSEAT amendment K-1: one window kit for every vendor

## Context

This amends `plans/phase-plan-v1-seats-FIRSTSEAT.md` (roadmap Phase 0). Its lane E (SL-4)
delivered IF-0-FIRSTSEAT-2 with Gemini-bound launch, board, reducer and CLI code, so no Codex,
Claude or Grok row window can run (principle 5). This amendment adds the lanes toward
EC-FIRSTSEAT-6. It changes no roadmap text and no EC.

**Owner: FIRSTSEAT.** FIRSTSEAT owns the vendor-parametric window kit, for these reasons:
- The roadmap assigns IF-0-FIRSTSEAT-2 and EC-FIRSTSEAT-6 to FIRSTSEAT.
- Its lane E owns `seat_window.py`, which `cli.py` only delegates to.
- Gemini's digests are FIRSTSEAT's (principle 4).
- JAILCORE SL-3.5 supplied only the profile-sourced `WindowRows` seam.

Vendor phases supply data and run and record their own windows. If a vendor phase owned the
kit, the other vendors would wait on its lanes. A JAILCORE erratum would reopen a phase whose
lanes have landed.

**Records-only notes in other plans.** Each note is dated, and none changes a lane's files or
an EC:
- CODEX: the ruling names FIRSTSEAT as the kit owner.
- JAILCORE: SL-3.5 delivered the profile rows only.
- CLAUDENET: names the extended kit and its Claude lane. The open item about the exception
  literal is now a dated resolution.
- GROK: S-2 is resolved in source, and the jailed Grok branch uses the board-leg bracket.
- FIRSTSEAT: SL-4 points here.

**Design.** The design is frozen in `plans/artifacts/seats-window-kit-k1-contract.md`, r4 (the
**contract**, sha256 `12a7d96e639846c2f3868434ca1faca837113614ca138c866f2b69592c20c3b2`). This
plan cites the contract and does not restate it:

| Topic | Contract |
|---|---|
| Supplier protocol, the closed supplier table and discovery | §3, §4 |
| Launch, credential-seam, bracket and terminal deltas to I-11, I-12 and I-15 | §5 |
| The run binding and the completion receipt | §6 |
| Reducer rules R1–R10 (only a vendor's own record changes that vendor's row, using the full key and snapshot-based expiry) | §7 |
| Grants and the CLI | §8 |
| The launch envelope, enforced before dispatch, and the login precondition | §9 |
| Per-vendor appendices, including the Codex A-C1 gate | §10 |
| A degraded Grok co-seat on another vendor's window | §14 |
| Acceptance tests K1-T1–T9, start gates K1-G1–G5, rulings Q-C(b) and Q-D | §15 |
| Pins, sequencing and falsifiers F1–F16 | §11–§13 |

**Owner decisions (2026-11-21).** Each is recorded in the owner's wording and implemented by
SL-5:

- **O-1, expiry.** "Approve, with launch snapshot (Recommended)". A record fails only on its
  own vendor's expired exception, or on a co-seat's exception that had already expired when it
  ran; that exception is recorded at launch and checked against the run time. Gemini's first
  window keeps verifying after 12-04, and the other freshness and key checks are unchanged.
  Implemented in contract §7 R6, including its legacy-W1 rule.
- **O-2, grants.** "Same binding, 1 attempt (Recommended)". Each vendor window gets its own
  grant, bound to host, context, time window, packet and launch budget. It allows ONE attempt
  by default, and a second needs the owner's explicit OK. A wrong host, replayed or corrupted
  state, or a duplicate run is refused before any login is used. Implemented in contract §8,
  which reuses W1's journal and witnesses and separates eligibility from the atomic claim.
- **Logins.** "Keep the full board (Recommended)". Each vendor window runs the real four-seat
  board. The owner keeps all four logins current on the designated host, and windows are
  batched per session. Implemented in contract §9.3.

**Inputs.** The digests in the contract's opening table and the content inputs it lists.
Nothing here pins a commit.

**Skill.** `claude-plan-phase`, in amendment form (the `plans/amendments/` precedent). The work
has several lanes, an interface freeze and content gates, and it amends a pipeline phase.

## Interface Freeze Gates

- [ ] IF-0-FIRSTSEAT-6 — contract §3 to §9: `WindowVendorData` v2, the supplier protocol,
  `SUPPLIERS` and discovery, the launch and board deltas, the credential seam,
  `_window_bracket`, the terminal classes, the run binding, R1–R10, `WINDOW_GRANTS` with
  eligibility and claim, the CLI and the launch envelope.

## Lane Index & Dependencies

SL-5 — K1-KIT: vendor-neutral kit, grants, reducer, CLI and launcher
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

**Content gates.** Each is checked on the lane's base tree, never by commit.
- **SL-5:** the base holds the contract's content inputs (the W1 grant, the stage-bound read
  receipt and its producer, the row-only reducer and Gemini's co-seats) and main's Grok
  `status` action. SL-5 merges after the W1 release is cut (contract §12).
- **SL-6:** may be written against IF-0-FIRSTSEAT-6 while SL-5 is in review, and lands after
  it.
- **SL-7:** contract §10.C's gate.
- **SL-8:** contract §10.D's gate.

**Order and rough size:** SL-5 (large), SL-6 (medium), SL-9 (small), then SL-7 (medium, after
CLAUDENET), then SL-8 (medium, after GROK's measured surface). Codex's row window can run once
SL-5 and SL-6 are in an installed release and the Codex grant is set.

## Lanes

Test commands run from `phase-loop-runtime/`.

### SL-5 — K1-KIT: vendor-neutral kit, grants, reducer, CLI and launcher

- **Scope**: Contract §2 to §9, on both sides of the frozen interface. Gemini W1 production and
  admission stay byte-identical.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window_grants.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_gemini.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_profiles.py`, `phase-loop-runtime/tests/test_seat_profiles.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/tests/test_seat_window_vendor_neutral.py`, `phase-loop-runtime/tests/test_seat_window_grants.py`, `phase-loop-runtime/tests/data/seat_window_gemini_k1_golden.json`, `phase-loop-runtime/tests/test_seat_qualification_host_context.py`, `phase-loop-runtime/tests/test_seat_jail_qualification_entry.py`, `phase-loop-runtime/tests/test_panel_invoker.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`
- **Interfaces provided**: IF-0-FIRSTSEAT-6
- **Interfaces consumed**: IF-0-FIRSTSEAT-2 (pre-existing), I-11, I-12 and I-15 (pre-existing), IF-0-JAILCORE-1 to IF-0-JAILCORE-3 (pre-existing), the contract's content inputs (pre-existing on the base)
- **Parallel-safe**: no
- **Named parts.**
  - `seat_profiles.py`: `WindowVendorData`, `register_window_data` and `GEMINI_WINDOW_DATA`.
  - `panel_invoker.py`, in the kit section (contract §5 and §9.1):
    - the `credential_mode` and `copy_transform` keywords of `_prepare_jailed_codex` and
      `_prepare_jailed_claude`, default `live`, with production behaviour unchanged at the
      default. SL-5 owns the Claude seam because the plan validator's ownership check (D)
      refuses two lanes owning `panel_invoker.py`;
    - the hook calls inside `_exec_jailed_codex_leg`, in Gemini's order;
    - `window_board=` routing in `_parent_infer`, and the reservation at the jailed Claude
      dispatch;
    - the ledger reservation in `launch_provider` and `run_provider`;
    - the president `invoke` wrapper in `window_board_launch`;
    - the reservation before `board_preflight_requalify`.

    SL-5 adds no Grok or Claude hook call site.
  - `test_panel_invoker.py`: the `seats_firstseat_exec_record_window_*` tests, edited only for
    the renamed result fields.
  - Inventories: entry by entry.
- **Proof checkpoints.** SL-5.2's tests are written first, against IF-0-FIRSTSEAT-6, and
  fail red. Each checkpoint turns its own subset green:
  1. golden and R1–R10: F1–F7, F10–F12, F14;
  2. grants, run binding and completion receipt: F8, F13;
  3. launcher, board, seam, hooks and ledger: F9, F16, K1-T3–T5, K1-T8 (SL-5 part);
  4. CLI and discovery: F15.
- **Stop rules.** Stop and report if:
  - the golden (F10) or the W1 grant behaviour cannot stay byte-identical;
  - a change touches `seat_jail_qualification.py`, `agy_qualification.py`,
    `gemini_heartbeat.py`, or `terminal_verdict` and its helpers;
  - `tests/test_agy_qci.py` or `tests/data/seat_profile_digests_jailcore.json` would change;
  - a jail builder, filter or allowlist file would change;
  - any source file owned by CLAUDE, CLAUDENET, CODEX or GROK would need an edit;
  - a `claude_seat_transport.SDK_PROOF_REGIONS` entry other than `_prepare_jailed_claude`
    (the seam) and `launch_provider` (the ledger reservation) would change, or `audit-order`
    fails after the change.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | (none) | `tests/data/seat_window_gemini_k1_golden.json`, `tests/test_seat_window_vendor_neutral.py` | the golden and its test (F10), captured from the base at a fixed clock | `pytest tests/test_seat_window_vendor_neutral.py -k golden` |
| SL-5.2 | test | SL-5.1 | `tests/test_seat_window_vendor_neutral.py`, `tests/test_seat_window_grants.py` | F1–F9, F11–F16, K1-T1–T5, K1-T8 (SL-5 part), K1-T9 and K1-G3, with a synthetic vendor registered in a fixture; F15 runs in a fresh process. The Claude seam goes through the real `_prepare_jailed_claude`, with the provider stubbed at its spawn boundary: `live` is byte-for-byte production, `none` builds no credential, and `expired` applies the transform. | `pytest tests/test_seat_window_vendor_neutral.py tests/test_seat_window_grants.py` |
| SL-5.3 | impl | SL-5.2 | `seat_profiles.py`, `seat_window_supply.py`, `seat_window_supply_gemini.py`, `seat_window.py` | (none) | `pytest tests/test_seat_window_vendor_neutral.py tests/test_seat_window_grants.py tests/test_seat_qualification_host_context.py` |
| SL-5.4 | impl | SL-5.3 | `panel_invoker.py`, `tests/test_panel_invoker.py`, inventories | (none) | `pytest tests/test_panel_invoker.py -k "window or codex" tests/test_seat_window_vendor_neutral.py` |
| SL-5.5 | verify | SL-5.4 | lane files | all | the frontmatter `suite_command` with `tests/test_seat_launch_helpers_trusted.py` and `tests/test_seat_profiles.py`, then, from the repository root, `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.claude_seat_transport audit-order --repo . --base origin/main` |

### SL-6 — K1-CODEX: Codex supplier adapter

- **Scope**: Contract §10.B as `seat_window_supply_codex.py`, which registers Codex's window
  data, plus the provider-free proof of assumption A-C1.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_codex.py`, `phase-loop-runtime/tests/test_seat_window_supply_codex.py`, `phase-loop-runtime/tests/test_seat_window_codex_provider_free.py`
- **Interfaces provided**: the Codex window supplier
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), IF-0-CODEX-1 to IF-0-CODEX-5 (pre-existing), the provider-free loopback harness of `tests/test_seat_codex_provider_free.py` (pre-existing)
- **Parallel-safe**: yes
- **Stop rules.** Stop if:
  - A-C1 fails;
  - a file owned by CODEX would need an edit;
  - Codex's profile or allowlist digest would change;
  - contract §10.B's facts need a new launch kind.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-6.1 | test | (none) | `tests/test_seat_window_supply_codex.py` | registration, kinds, argv, stream facts, scope and refresh outcomes, and F16 through the real `_prepare_jailed_codex` with the provider stubbed at its spawn boundary; one fixture context through `cli_main` to a record that `verify --vendor codex --window row` passes and that changes only `vendor:codex` | `pytest tests/test_seat_window_supply_codex.py` |
| SL-6.2 | test | SL-6.1 | `tests/test_seat_window_codex_provider_free.py` | K1-T6 (start gate for SL-6.3) and K1-T7 | `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 pytest tests/test_seat_window_codex_provider_free.py` |
| SL-6.3 | impl | SL-6.2 | `seat_window_supply_codex.py` | (none) | `pytest tests/test_seat_window_supply_codex.py tests/test_seat_profile_codex.py` |
| SL-6.4 | verify | SL-6.3 | lane files | all | the frontmatter `suite_command` and `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 pytest tests/test_seat_window_codex_provider_free.py` |

### SL-7 — K1-CLAUDE: Claude supplier adapter

- **Scope**: Contract §10.C as `seat_window_supply_claude.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_claude.py`, `phase-loop-runtime/tests/test_seat_window_supply_claude.py`
- **Interfaces provided**: the Claude window supplier
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), IF-0-CLAUDENET-1 to IF-0-CLAUDENET-3 (content gate), IF-0-CLAUDE-1 (pre-existing), `seat_claude_containment.refreshed_in_jail` (content gate), the Q-C(b) print-path transport observer (content gate)
- **Parallel-safe**: yes
- **Stop rules.** Stop if:
  - start gate K1-T8 (Claude part, through the print-path observer) is not green;
  - any Claude, SDK or CLAUDENET file would need an edit. The `_prepare_jailed_claude`
    credential seam is SL-5's (IF-0-FIRSTSEAT-6), and SL-7 consumes it;
  - OD-3b has recorded no default.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-7.1 | test | (none) | `tests/test_seat_window_supply_claude.py` | as SL-6.1 for Claude, plus the hook order through the observer with the transport spawn stubbed, a refused non-default transport, and the key's `variant` | `pytest tests/test_seat_window_supply_claude.py` |
| SL-7.2 | impl | SL-7.1 | adapter | (none) | `pytest tests/test_seat_window_supply_claude.py tests/test_seat_claude_containment.py` |
| SL-7.3 | verify | SL-7.2 | lane files | all | the frontmatter `suite_command`, then, from the repository root, `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.claude_seat_transport audit-order --repo . --base origin/main` |

### SL-8 — K1-GROK: Grok supplier adapter

- **Scope**: Contract §10.D as `seat_window_supply_grok.py`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_window_supply_grok.py`, `phase-loop-runtime/tests/test_seat_window_supply_grok.py`
- **Interfaces provided**: the Grok window supplier
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), IF-0-GROK-1 (pre-existing; content gate), IF-0-GROK-2 (pre-existing; content gate), IF-0-GROK-3 (pre-existing; content gate: GROK SL-3's leg with its hook call), the measured jailed surface from GROK SL-6 (pre-existing; content gate)
- **Parallel-safe**: yes
- **Stop rules.** Stop if:
  - start gates K1-G1 or K1-T8 (Grok part) are not met;
  - a window launch needs the route's retry;
  - no refused-intended signature is measured;
  - Grok's profile digest would change.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-8.1 | test | (none) | `tests/test_seat_window_supply_grok.py` | as SL-6.1 for Grok, plus an unmeasured tool surface refused before the board | `pytest tests/test_seat_window_supply_grok.py` |
| SL-8.2 | impl | SL-8.1 | adapter | (none) | `pytest tests/test_seat_window_supply_grok.py tests/test_grok_tool_surface.py` |
| SL-8.3 | verify | SL-8.2 | lane files | all | the frontmatter `suite_command` and `tests/test_seat_window_supply_grok.py` |

### SL-9 — Documentation & spec reconciliation

- **Scope**: Document the kit, the Codex row window, grants, the envelope and the login
  precondition. Record SL-7, SL-8 and the Pi revision as pending, and update the manifest.
- **Owned files**: `plans/evidence/seat-qualification/README.md`, `docs/review-seats-readiness.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `plans/manifest.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-FIRSTSEAT-6 (SL-5), the Codex window supplier (SL-6)
- **Parallel-safe**: no
- **Notes**: SL-7 and SL-8 are not producers for this reducer. It records them as pending and
  never claims they are complete; their vendor phase's records PR reports their landing. No
  row status changes here.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-9.1 | test | (none) | (none) | (none) | `pytest tests/test_seat_reference_inventory.py tests/test_legible_roadmap_contract.py` |
| SL-9.2 | docs | SL-9.1 | lane files | (none) | `python ../skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py ../plans/amendments/seats-FIRSTSEAT-K1-window-kit.md` |

## The owner's window packet, and what each vendor phase still adds

**Per-window packet.**
- **Grant.** One grant per `(vendor, window)`, for one attempt (contract §8).
- **Envelope.** The model-capable starts of contract §9.2: 14 for a Gemini, Codex or Claude
  context, 13 for Grok. On top of that, line items A1–A7 are each capped. The grant's
  `launch_envelope` binds them, and every start is reserved before it is dispatched
  (contract §9.1).
- **Logins.** The board still needs all four logins, as approved; each must be current on the
  designated host. The operator runs `seat-window ready` first (§9.3). A degraded Grok
  co-seat does not block another vendor's window, but a missing Grok login does
  (contract §14), subject to gate K1-G3 before the first post-Train-A grant.
- **Spent attempts.** A composition refusal after the claim spends the attempt.

| Phase | Code still to add | Live work and records |
|---|---|---|
| CODEX | Nothing. | The owner-approved grant change for `("codex","row")`, landed by the kit owner; a release with SL-5 and SL-6 installed, with its EC-EXECFIND-2 pass on the current key; LA-2 for all four vendors; LA-3; the records PR (CODEX SL-docs.3, EC-CODEX-4). |
| CLAUDENET | Nothing beyond IF-0-CLAUDENET-1 to IF-0-CLAUDENET-3, which are already planned. The print-path observer is CLAUDE's (Q-C(b)). | After SL-7: grant, release, LA-2, LA-3 and the records PR (EC-CLAUDENET-4). |
| GROK | SL-3: the jailed leg calls the `window_board=` hook inside itself, in Gemini's order. SL-6: the measured jailed surface. K-1 registers Grok's window data. K1-G2 gates the first Grok grant. | After SL-8: grant, release, LA-2, LA-3 and the records PR (EC-GROK-4). |
| PI | It waits on the contract's Pi revision (§10.E), which FIRSTSEAT owns. | — |

## Verification

Run each lane's own table. For the whole amendment, run the frontmatter `suite_command`. Each
code PR also runs `tests/test_agent_cli_scratch_inventory_1147.py`,
`tests/test_seat_launch_helpers_trusted.py` and `tests/test_seat_reference_inventory.py`, and a
Gate A-shaped tree built from an installed wheel. Shared-host rule: only the listed files,
serially without `-n`, under `timeout`, after the headroom check; never a full suite.

Lanes stop at code and records. These are owner actions outside this plan (validator warning
N): cutting and installing a release, minting a grant, the grant change, and every live window.
No lane makes a live provider call or runs on a seat host. SL-6.2 is provider-free.

## Execution Notes

- **One PR per lane.** SL-5 lands first, then SL-6 and SL-9. SL-7 and SL-8 land when their
  gates open.
- **EC-FIRSTSEAT-6 coverage.** This amendment's acceptance items prove its kit, Gemini and
  Codex parts. The EC closes only when SL-7, SL-8 and the Pi revision have landed, and
  FIRSTSEAT stays open on it until then. Nothing transfers after FIRSTSEAT exits.
- **Single-writer files.** `panel_invoker.py`, `seat_profiles.py` and `test_panel_invoker.py`
  are shared with TEAMHOST, CODEX, GROK, PI, CLAUDENET and v11 PANELSPLIT. Here only SL-5
  writes them, in its named parts. Whichever lands second rebases. If PANELSPLIT has moved the
  window section, SL-5 edits the successor and records the path.
- **Rebase.**
  - SL-5's base must hold the content of the W1 kit fixes (the stage-bound read receipt and
    its producer, the row-only reducer, the co-seats), the content of the W1 opening (the
    grant, journal and witnesses), and main's Grok `status` action.
  - W0's two-session change re-stamps the roadmap pin and touches `CHANGELOG.md`,
    `seat_launch_references.json` and the edited phase plans' frontmatter. Whichever lands
    second re-stamps this file's frontmatter, and the inventories are union-resolved. The
    contract does not pin the roadmap.
- **Pin accounting: the Claude SDK proof binding.** SL-5's edits to `_prepare_jailed_claude`
  (the seam) and `launch_provider` (the ledger) are inside
  `claude_seat_transport.SDK_PROOF_REGIONS`, so the SDK proof-input binding moves with SL-5.
  `seat_profiles.py` is also a whole-file SDK proof input (`SDK_PROOF_FILES`), and SL-5's
  `WindowVendorData` v2 and its provider-boundary hook edit it, so that input moves too. It
  is an SL-5-owned file, not a `SDK_PROOF_REGIONS` entry, so the regions stop rule does not
  apply to it. `claude_seat_sdk.ADMITTED` is `False`, so no SDK receipt is renewed. SL-5.5's
  `audit-order` run must pass after the move, and so must SL-7.3's.
- **Requalification.** None, by contract §11, on the conditions it states: the `live`
  defaults, the hook call sites, the legacy W1 check and the stop rules hold. Only
  `runtime_digest` and `release_identity` move.
- **Warning P.** EC-FIRSTSEAT-1 to EC-FIRSTSEAT-5 stay proven by the parent FIRSTSEAT plan's
  evidence. This amendment neither changes nor re-proves them.
- **Settled after review.**
  - Q-1: FIRSTSEAT stays open on EC-FIRSTSEAT-6 until SL-7, SL-8 and the Pi revision land,
    and closes on the roadmap's own evidence for it. This creates no new sequencing
    dependency: JAILCORE's lanes have already landed, so the roadmap's note placing JAILCORE
    after FIRSTSEAT's exit is spent.
  - Q-2: the trust boundary in contract §1 is accepted, as for W1.
- **Rulings (contract §15.3).** Q-C(b): `print` is the recorded default, and CLAUDE's observer
  lands on the print path. Q-D is a contingency stop on SL-6.
- **Stall rule.** The diagnosis after r3 binds: r4 is the convergence round. Later findings go to
  the code review of the lane that owns the test (contract §15).
- **Known destructive changes**: `WindowBoardResult.canonical_gemini` and `.gemini` are removed
  (contract §5.3). Every reader is in SL-5's files.
- **Rollback.** Revert the lane. The W1 records, the W1 grant and the golden are unaffected.

## Acceptance Criteria

- [ ] EC-FIRSTSEAT-6 — proven by `pytest tests/test_seat_window_vendor_neutral.py tests/test_seat_window_grants.py` (F1–F9, F11–F15, K1-T1–T5, K1-T8 SL-5 part, K1-T9), entered through `cli_main`, `qualify`, `verify_records`, `reduce_readiness` and `export_records`, with a fixture vendor registered only through `register_window_data` and F15 run in a fresh process; falsified by any of: a passing record changing another vendor's row; a failing partition blocking another; a grant opening another pair, or one claimed after an auth call; a stale key part passing; an expired snapshot entry passing; a relabelled, replayed or restamped record passing. Path-entered control: real retained source files in a 0700 fixture directory, and the real grant journal and witnesses.
- [ ] EC-FIRSTSEAT-6 — Codex, proven by `pytest tests/test_seat_window_supply_codex.py` and `PHASE_LOOP_REQUIRE_LIVE_JAIL=1 pytest tests/test_seat_window_codex_provider_free.py` (K1-T6, K1-T7); falsified by any of: a Codex record carrying Gemini's profile, allowlist or contract digest passing; a window launch retrying; `refused_intended` assigned to an incomplete stream or to a jail or proxy failure; the production `_prepare_jailed_codex` path changing. Path-entered control: the real `_prepare_jailed_codex` with the provider stubbed at its spawn boundary, and the real pinned binary under the loopback harness.
- [ ] EC-FIRSTSEAT-7 — proven by `pytest tests/test_seat_window_vendor_neutral.py -k "golden or legacy or registry_change"` (F10, F12's legacy cases, F14), with `tests/test_agy_qci.py` and the profile-digest receipt unchanged; falsified by any golden byte, Gemini argv or binding digest differing, by W1 refusing after a candidate row is added, or by the legacy rule applying without its journal. Path-entered control: the real Gemini window data and its supplier over the unedited `seat_jail_qualification`.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `plans/phase-plan-v1-seats-FIRSTSEAT.md`, `plans/phase-plan-v1-seats-CODEX.md`, `plans/phase-plan-v1-seats-JAILCORE.md`, `plans/phase-plan-v1-seats-CLAUDENET.md`, `plans/phase-plan-v1-seats-GROK.md`, `plans/evidence/seat-qualification/README.md`, `docs/review-seats-readiness.md`
- evidence paths: `phase-loop-runtime/tests/test_seat_window_vendor_neutral.py`, `phase-loop-runtime/tests/data/seat_window_gemini_k1_golden.json`
- redaction posture: `metadata_only`
- downstream handling: none; the roadmap is unchanged, and the plan notes listed in Context land with this plan
