---
phase_loop_plan_version: 1
phase: PANEL
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 124554d1ce4232b60c71e8fc71d3f4e334c6d63080f8d62f498cbed68d08eeae
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py verify;
      PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_panel_lanes.py
      phase-loop-runtime/tests/test_panel_lens_delivery.py
      phase-loop-runtime/tests/test_panel_doc_contract.py
      phase-loop-runtime/tests/test_president_heartbeat_1001.py
      phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py
      phase-loop-runtime/tests/test_train_review_packet.py
      phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py
      phase-loop-runtime/tests/test_president_wiring.py
      phase-loop-runtime/tests/test_train_review_monitoring_policy.py
      phase-loop-runtime/tests/test_review_monitor_policy.py
      phase-loop-runtime/tests/test_advisor_board_config.py
      phase-loop-runtime/tests/test_advisor_board_composition.py
      phase-loop-runtime/tests/test_advisor_board_presets.py
      phase-loop-runtime/tests/test_president_ladder_config.py;
      PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md;
      PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.goal_coverage import check_goal_coverage; r=check_goal_coverage(repo=Path("."), plan=Path("plans/phase-plan-v10-PANEL.md"), roadmap=Path("specs/phase-plans-v10.md")); assert not r.unreferenced_ids and not r.dangling_refs, r';
      uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime
---

# PANEL: Panel Vendor Fallback and Lanes

## Context

Plans agent-harness#1078 (roadmap: agent-harness#1079). The EC-PANEL-N criteria are the contract, referenced and never restated. Today:
- `compose_review_board` backfills from a global `LENS_CYCLE`.
- The presets are fixed seat tuples.
- `config.py` reads `[president]` from the user and repository files.
- `review_policy_for_tier` (~427) requires four named seats. `invoke_board` (~8502) and `runner.py` (~8537) consume it.
- Per-seat instructions are assigned at ~8835 and ~9324–9328.
- `heartbeat_only` seats the frozen `DEFAULT_BOARD` (`governed_review.py` ~423, `cli.py` ~2033).

## Interface Freeze Gates

- [ ] IF-0-PANEL-1 — the names SL-0's frozen tests import. EC-PANEL-1/4/5 carry the behaviour.
  - `advisor_board.config`:
    - `ResolvedLens(name, text, kind)`, `PanelLane`, `PanelTable`, `ExplicitProfileSeats(seats, path, provenance)`;
    - `resolve_panel_table(task, *, user_path, repo_dir, base_revision) -> ResolvedPanelTable`, which carries the table, a source label and provenance;
    - `validate_panel_change(repo_dir, *, base_revision, head_revision)`, which raises `BoardConfigError`;
    - `panel_regate_required(repo_dir, *, gated_revision, target_head) -> bool`, true when `[panel.*]` or the repository `governance.toml` `panel` list changed;
    - `PanelRunSnapshot(user_table, user_digest, user_profile)` from `snapshot_panel_run(*, user_profile=None)`, taken once at run start. It holds user-side inputs only;
    - `PanelContext(snapshot, resolved_table, explicit_profile, composed, gated_revision)` from `build_panel_context(task, snapshot, *, repo_dir, base_revision, head_revision, monitoring_policy, repository_profile=None)`. The builder runs at gate time with explicit revisions:
      - `base_revision` is the target head, from the fetched target branch resolved at gate time; `gated_revision = base_revision`;
      - it reads `[panel.*]` at `base_revision` and runs `validate_panel_change(base_revision=…, head_revision=…)`; a non-landing `advisor-board` run passes `head_revision=None`, which skips validation;
      - it resolves the explicit profile from `repository_profile`, read at `base_revision` (the GOVSETUP injection point), over `snapshot.user_profile`, labelled with `gated_revision`;
      - it composes under that policy's probes and preflight;
      - it is rebuilt on every re-gate.
  - `advisor_board.presets.BUILTIN_LENS_TEXT`.
  - `advisor_board.composition.compose_panel_board(table, *, is_available, auth_ok, preflight) -> ComposedPanel(board, seat_lenses, fallback_lanes, unfilled_lanes)`. `seat_lenses` is the only lens source.
  - `panel_invoker`:
    - `panel_landing_policy(tier, *, context) -> ReviewLandingPolicy`;
    - `ReviewLandingPolicy` gains additive `min_distinct_vendors: int | None = None` and `min_usable_seats: int = 0`. The defaults keep today's rule for every tier; `panel_landing_policy` sets the floor to 2 for `plan` and `production_code` only;
    - `evaluate_landing(policy, *, usable_legs, president_ruling, context, user_digest_now) -> LandingDecision`, the one evaluator. `invoke_board` calls it;
    - `invoke_board(..., panel_context: PanelContext | None = None)`. A `plan` or `production_code` landing without a context is refused with `panel_context_required`;
    - `PanelLabels`, carried on `PanelResult`, the `advisor-board` JSON and landing records;
    - `_seat_instructions(base, lens) -> tuple[str, str]`, which reads `context.composed.seat_lenses[<seat key>]`. The label is `prompt` iff a non-empty section was appended.
- [ ] IF-0-PANEL-2 — `advisor_board.lens_frame.render_lens_section(lens: ResolvedLens) -> str` (slice 2).

## Lane Index & Dependencies

SL-0 — Tests-first frozen corpus (every EC-PANEL node)
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Slice 1: lane tables, composition, landing minimum, labels
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Slice 2: lens in each seat's instructions
  Depends on: SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation and phase reducer (lands with SL-2)
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Tests-first frozen corpus (every EC-PANEL node)

- **Scope**: Land every PANEL falsifier before any production edit, and record the `content_tdd_receipt.v1` receipt against the pre-implementation base (EC-PANEL-0, as EC-PRESROUTE-0).
- **Owned files**: `phase-loop-runtime/tests/test_panel_lanes.py`, `phase-loop-runtime/tests/test_panel_lens_delivery.py`, `phase-loop-runtime/tests/test_panel_doc_contract.py`, `phase-loop-runtime/tests/data/panel_code_review_snapshot.golden.json`, `phase-loop-runtime/tests/panel_content_tdd_adapter.py`, `.phase-loop/evidence/PANEL/content-tdd-receipt.json`, `.phase-loop/evidence/PANEL/content-tdd-receipt.red.stdout.log`, `.phase-loop/evidence/PANEL/content-tdd-receipt.red.stderr.log`
- **Interfaces provided**: the frozen PANEL falsifiers, the base-captured code-review snapshot golden, and a `content_tdd_receipt.v1` receipt.
- **Interfaces consumed**: `phase_loop_runtime.tdd_receipts` (pre-existing); the adapter pattern of `presroute_content_tdd_adapter.py` (pre-existing).
- **Parallel-safe**: no (SL-1 to SL-3 consume its frozen bytes and never edit them).
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_panel_lanes.py`, `phase-loop-runtime/tests/data/panel_code_review_snapshot.golden.json` | `ec1_*`–`ec5_*` (one node group per EC-PANEL-1..5 falsifier), `ec6h_*` and `ec3e_*` | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py` |
| SL-0.2 | test | SL-0.1 | `phase-loop-runtime/tests/test_panel_lens_delivery.py` | `ec6_*` on the brokered, TUI and native-fill routes | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lens_delivery.py` |
| SL-0.3 | test | SL-0.2 | `phase-loop-runtime/tests/test_panel_doc_contract.py` | `ec7_*` | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_doc_contract.py` |
| SL-0.4 | impl | SL-0.3 | `phase-loop-runtime/tests/panel_content_tdd_adapter.py`, `.phase-loop/evidence/PANEL/**` | — | `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py record-red` |
| SL-0.5 | verify | SL-0.4 | `.phase-loop/evidence/PANEL/**` | receipt verifies | `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py verify` |

Rules for the frozen corpus:
- **Readiness keys.** A node skips in ordinary runs only while its slice's symbol is absent:
  - `ec1_*`–`ec5_*` and `ec3e_*` key on `resolve_panel_table`;
  - `ec6h_*` keys on `_seat_instructions`;
  - `ec6_*` and `ec7_*` key on `render_lens_section`.

  `PHASE_LOOP_TDD_EXPECT_PANEL=1` disables every skip. The acceptance commands and the suite run with it, and the adapter's `verify` asserts zero skips at head. The adapter mirrors `presroute_content_tdd_adapter.py`.
- **`ec1_*`** pins, against the base-captured golden:
  - `CODE_REVIEW_BOARD`, `resolver._STANDIN_CODE_REVIEW` and `DEFAULT_BOARD`;
  - every preset task's all-available `compose_panel_board` seats.

  The golden stores `(seat key, harness, effort, lens)`, with model compared through its registry pin; the receipt binds it.
- **`ec3e_*`** has one node group per entry point: `runner.py`, the governed gate, `run-train` and `advisor-board`. Each is driven through the entry point itself, at the tiers that entry point lands: `runner.py` at `production_code`, the governed gate and `cli.py` at `plan` and `tests_only`. It covers:
  - the configured minimum, both ways;
  - a mid-run user-file edit being refused;
  - a target-head change to `[panel.*]`, or to only the repository profile `panel` list, forcing a re-gate that enforces the new requirements (before the first gate and after one);
  - the landing record and `advisor-board` JSON carrying every EC-PANEL-5 label, matching the resolved configuration and seat outcomes;
  - an invalid `[panel.*]` change being refused;
  - a missing context being refused.
- **`ec6h_*`** stubs `lens_frame` in `sys.modules` and covers the slice-1 hook on all three routes. A hook defect found in SL-2 reopens SL-1.
- **One group per falsifier.** Each EC-PANEL-N falsifier in the roadmap gets its own node group. A later test correction restarts SL-0.

### SL-1 — Slice 1: lane tables, composition, landing minimum, labels

- **Scope**: Implement IF-0-PANEL-1 and make SL-0's `ec1_*`–`ec5_*` nodes green.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/advisor-boards.example.toml`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_advisor_board_presets.py`, `phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py`, `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_train_review_monitoring_policy.py`, `phase-loop-runtime/tests/test_president_heartbeat_1001.py`, `phase-loop-runtime/tests/test_review_monitor_policy.py`
- **Interfaces provided**: IF-0-PANEL-1.
- **Interfaces consumed**: SL-0's frozen falsifiers and golden; `_reject_unknown`, `repo_board_config_path` and the `[president]` loader in `config.py` (pre-existing); `PanelResult.usable_legs` (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | the eight existing test files above | only assertions that pin the frozen `heartbeat_only` board, `LENS_CYCLE` backfill, "a missing vendor fails its seat", or composition refusing below `FLOOR_SEATS` change; each change is listed in the landing record | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_review_monitor_policy.py` |
| SL-1.2 | impl | SL-1.1 | `config.py`, `presets.py`, `fixtures/advisor-boards.example.toml` | — | — |
| SL-1.3 | impl | SL-1.2 | `composition.py`, `panel_invoker.py`, `runner.py`, `train_runner.py` | — | — |
| SL-1.4 | impl | SL-1.3 | `governed_review.py`, `cli.py`, `CONTRACTS.md` | — | — |
| SL-1.5 | verify | SL-1.4 | all of the above | `ec1_*`–`ec5_*`, `ec3e_*`, `ec6h_*` plus the owned suites | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_president_ladder_config.py phase-loop-runtime/tests/test_advisor_board_config.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_advisor_board_presets.py phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py phase-loop-runtime/tests/test_president_wiring.py phase-loop-runtime/tests/test_train_review_monitoring_policy.py phase-loop-runtime/tests/test_president_heartbeat_1001.py phase-loop-runtime/tests/test_review_monitor_policy.py` |

Task detail (files and seams only; the behaviour is EC-PANEL-1..5 and IF-0-PANEL-1):
- **SL-1.2** — `config.py`: the `[panel.*]` loader, snapshot, context builder, change validation and re-gate check. `[president]` is untouched. `presets.py`: `BUILTIN_LENS_TEXT` and the built-in tables.
- **SL-1.3** — `composition.py`: `compose_panel_board`. `compose_review_board` is unchanged and serves only the import-time snapshots. `panel_invoker.py`: the policy, the evaluator, labels, the context refusal and the hook. The entry points (`runner.py`, `train_runner.py`) snapshot at run start, build the context at their gate, and pass it.
- **SL-1.4** — `governed_review.py` and `cli.py` do the same, re-gating at the governed merge and at `cli.py`'s governed landing. N1–N3 carry over as the roadmap states. Declared lens names follow EC-PANEL-1 with no prefix rule; N4 is covered by the fallback and SL-3's recovery docs.

### SL-2 — Slice 2: lens in each seat's instructions

- **Scope**: Implement IF-0-PANEL-2 and make SL-0's `ec6_*` nodes green (EC-PANEL-6).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/lens_frame.py`, `phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py`, `phase-loop-runtime/tests/test_train_review_packet.py`
- **Interfaces provided**: IF-0-PANEL-2.
- **Interfaces consumed**: IF-0-PANEL-1 (`ResolvedLens`, `_seat_instructions`, `ComposedPanel.seat_lenses`) from SL-1; the digest-bound frame builder in `panel_invoker.py` (pre-existing).
- **Parallel-safe**: no (consumes SL-1's hook; lands in one PR with SL-3).
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py`, `phase-loop-runtime/tests/test_train_review_packet.py` | update only assertions that pin identical seat instructions, and list each in the landing record | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py phase-loop-runtime/tests/test_train_review_packet.py` |
| SL-2.2 | impl | SL-2.1 | `advisor_board/lens_frame.py` | — | — |
| SL-2.3 | verify | SL-2.2 | `advisor_board/lens_frame.py` | `ec6_*` | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lens_delivery.py phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py phase-loop-runtime/tests/test_train_review_packet.py` |

SL-2.2's `render_lens_section` renders the fixed heading `Review lens (subordinate to the verdict protocol)`, then the lens name and text verbatim, then the precedence sentence. Slice 2's board bundle includes SL-1's hook and the frame builder, because slice 2 changes every frame without touching `panel_invoker.py`.

### SL-3 — Documentation and phase reducer (lands with SL-2)

- **Scope**: EC-PANEL-7's documentation and entry-doc coverage, and the phase reduction.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `docs/TEAM-ONBOARDING.md`, `.github/entry-doc-suppressions.json`, `.github/workflows/test.yml`, `CHANGELOG.md`, `.claude/docs-catalog.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal reducer).
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | docs | — | `.claude/docs-catalog.json` | — | `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if absent, record "docs-catalog rescan helper unavailable; manual catalog audit" |
| SL-3.2 | docs | SL-3.1 | the two docs, `.github/entry-doc-suppressions.json`, `CHANGELOG.md` | `ec7_*` | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_doc_contract.py` |
| SL-3.3 | verify | SL-3.2 | — | — | `git diff --exit-code origin/main -- specs/phase-plans-v10.md` |

SL-3.2 documents lane tables, lens declarations, the fallback, the minimum and its precedence, and the labels (EC-PANEL-7). It also covers:
- the `[president]` pointer for a single-vendor user;
- out-of-band recovery for an operator with fewer than four vendors when a base table goes invalid (N4);
- that a minimum of 1 means one distinct *vendor*, not one seat.

It keeps the entry-doc check covering those sections, and touches `.github/entry-doc-suppressions.json` only if a suppression must change. At closeout it sets `PHASE_LOOP_TDD_EXPECT_PANEL=1` in `.github/workflows/test.yml`, so a later rename of a readiness symbol fails CI instead of silently skipping.

## Execution Policy

- work-unit defaults: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-0: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-1: effort=`xhigh`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-2: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-3: effort=`medium`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- **Landing order.** Three landings, each with its own board and president:
  1. SL-0, first, as its own PR;
  2. SL-1 (slice 1);
  3. SL-2 with SL-3 (slice 2 plus docs), only after slice 1 has merged.
- **Cross-phase gates** (from the PANEL ruling and the DAG governance note in `specs/phase-plans-v10.md`):
  - GOVSETUP's plan is dispatch-held behind SL-1 (DAG note).
  - REVIEWTRUTH's EC-5 lane is held until its plan cites the ruling and SL-1 lands.
  - LEGLIFE's EC-4 lane is held until its plan cites the ruling.
  - The LEGLIFE-4 and REVIEWTRUTH-5 closeouts wait for SL-2.
  - This plan edits none of those phases.
- **Readings of earlier criteria** (from the president ruling on agent-harness#1079):
  - EC-GOVLEAN-5's "full board" is the board EC-PANEL-4 requires.
  - EC-GOVSETUP-4's "four seats" is today's four named seats (`min_distinct_vendors=None`), labelled as an effective minimum of 4 from the built-in source. Take GOVSETUP's no-profile golden after SL-1.
- **Touch-shape falsifier (named seams).** `panel_invoker.py`, `governed_review.py`, `cli.py` and `runner.py` are shared with HARDEN, REVIEWTRUTH, LEGLIFE and RESIDUAL, and in-flight EXECFIND work touches `governed_review.py`/`panel_invoker.py`. A landing whose diff rewrites an existing line of these files outside its named seams fails the phase. The named seams are:
  - in `invoke_board`: the policy call sites, the landing-evaluation site, `PanelResult` fields and the per-seat `effective_instructions` assignments (the hook only);
  - in each entry point (`runner.py`, `train_runner.py`, `governed_review.py`, `cli.py`): the board-selection line, the `invoke_board` call line, the run-start snapshot, the gate-time context build, the re-gate check, the label writers, and imports the switch leaves unused.

  Everything else is additive. Landings take their turn in manifest queue order among ready landings.
- **Single-writer files.**
  - SL-0: the three new test files, the snapshot golden, the adapter and the receipt.
  - SL-1: `config.py`, `composition.py`, `presets.py`, `CONTRACTS.md`, the example TOML, `governed_review.py`, `cli.py`, `runner.py`, `train_runner.py` and the eight existing test files it lists.
  - SL-1: `panel_invoker.py`, including the lens hook.
  - SL-2: `advisor_board/lens_frame.py` and the two frame-reading tests.
  - SL-3: the docs, `CHANGELOG.md` and the catalog.
- **Known destructive changes**:
  - SL-1 replaces every live board selection (the `compose_review_board` calls, `runner.py`'s `CODE_REVIEW_BOARD` and the `heartbeat_only` `DEFAULT_BOARD`) with `PanelContext.composed.board`.
  - SL-1 wraps the per-seat `effective_instructions` assignments in the lens hook; SL-2 changes no existing line.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/**`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `docs/advisor-board-capabilities-card.md`, `docs/TEAM-ONBOARDING.md`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-PANEL.md`, `plans/manifest.json`, `phase-loop-runtime/tests/test_panel_lanes.py`, `phase-loop-runtime/tests/test_panel_lens_delivery.py`, `phase-loop-runtime/tests/test_panel_doc_contract.py`, `phase-loop-runtime/tests/data/panel_code_review_snapshot.golden.json`, `.phase-loop/evidence/PANEL/content-tdd-receipt.json`
- redaction posture: `metadata_only`
- downstream handling: none

## Verification

Run after all lanes merge:

```bash
PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py verify
PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_panel_lens_delivery.py phase-loop-runtime/tests/test_panel_doc_contract.py
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_ladder_config.py phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py phase-loop-runtime/tests/test_train_review_packet.py phase-loop-runtime/tests/test_advisor_board_config.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_advisor_board_presets.py phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py phase-loop-runtime/tests/test_president_wiring.py phase-loop-runtime/tests/test_train_review_monitoring_policy.py phase-loop-runtime/tests/test_president_heartbeat_1001.py phase-loop-runtime/tests/test_review_monitor_policy.py
```

Plan-artifact checks:

- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-PANEL.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.planner_validation import validate_plan_dispatch_hints; f=validate_plan_dispatch_hints(Path("plans/phase-plan-v10-PANEL.md").read_text()); assert not f, f'`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.plan_manifest check --repo .`
- `git diff --exit-code origin/main -- specs/phase-plans-v10.md`

## Acceptance Criteria

All commands run with `PHASE_LOOP_TDD_EXPECT_PANEL=1`, so a missing frozen symbol fails instead of skipping.

- [ ] EC-PANEL-0 — proven by `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py verify`; falsified by a frozen test whose merge-time bytes differ from its freeze-time record, by missing RED output, or by any skipped PANEL node (`verify` asserts zero skips at head).
- [ ] EC-PANEL-1 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k "ec1 or ec3e"`; falsified by a path-entered `[panel.*]` table in a temporary user file or git fixture repository that a listed falsifier rejects being accepted, or the reverse, or by an import-time snapshot differing from the base golden.
- [ ] EC-PANEL-2 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k ec2`; falsified by `compose_panel_board` seating anything other than the first eligible vendor, or mis-recording an unfilled lane, across a parametrized availability, auth and preflight matrix.
- [ ] EC-PANEL-3 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k ec3`; falsified by `advisor-board`, the governed gate or `run-train` composing a different board for the same configuration.
- [ ] EC-PANEL-4 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k "ec4 or ec3e"`; falsified by any configured value 1–4 admitting a landing below it, refusing a qualifying one on panel composition, or dropping an explicit profile seat, at `invoke_board` or through any entry point.
- [ ] EC-PANEL-5 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k "ec5 or ec3e"`; falsified by a result or landing record lacking any label, or carrying one (profile path and provenance included) that disagrees with the resolved configuration or the seat outcomes.
- [ ] EC-PANEL-6 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lens_delivery.py`; falsified by a seat's lens name or text outside its authoritative instructions on any route, protocol text differing between two seats, or a `prompt` label without an appended section.
- [ ] EC-PANEL-7 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_doc_contract.py`; falsified by an accepted key or emitted label that is undocumented, a documented key the loader refuses, a missing `[president]` pointer or recovery section, or the entry-doc check not covering the sections.
