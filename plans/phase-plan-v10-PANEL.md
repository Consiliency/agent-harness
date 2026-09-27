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
      phase-loop-runtime/tests/test_panel_sl1_contracts.py
      phase-loop-runtime/tests/test_panel_lens_transport.py
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
    - `PanelContext(snapshot, resolved_table, explicit_profile, composed, gated_revision)` from `build_panel_context(task, snapshot, *, repo_dir, base_revision, head_revision, monitoring_policy, repository_profile=None, probes=None)`. The builder runs at gate time with explicit revisions:
      - `base_revision` is the target head, from the fetched target branch resolved at gate time; `gated_revision = base_revision`;
      - it reads `[panel.*]` at `base_revision` and runs `validate_panel_change(base_revision=…, head_revision=…)`; a non-landing `advisor-board` run passes `head_revision=None`, which skips validation;
      - it resolves the explicit profile from `repository_profile`, read at `base_revision` (the GOVSETUP injection point), over `snapshot.user_profile`, labelled with `gated_revision`. The profile shape it reads is the corpus's: `.phase-loop/governance.toml` at `base_revision` and `$XDG_CONFIG_HOME/agent-harness/governance.toml`, each listing seat aliases (`fable`, `sol`, `grok`, `gemini`) as `[tiers.<tier>] panel = [...]`; no other `[tiers.<tier>]` key lowers the minimum. A malformed or unreadable profile at `base_revision` or in the user file raises `BoardConfigError`, and the landing is refused. A `panel` value of `none` is refused at `plan` and `production_code` (EC-GOVSETUP-6). At `tests_only` and `docs_only`, `none` means no explicit seats, which is those tiers' built-in. Neither case is ever read as "no required seats" where seats are required. By maintainer decision (2026-09-27), IF-0-GOVSETUP-1 builds on this layout (see the SL-1 entry gates);
      - it composes under that policy's probes and preflight. `probes` is the one injectable probe seam: `PanelProbes(is_available, auth_ok, preflight)`, whose callables go to `compose_panel_board` unchanged. When it is `None` the default probes read `DEFAULT_HARNESS_REGISTRY.probe`, `executor_availability._probes_pass` and `gemini_heartbeat.require_capability`, and the builder reads `compose_panel_board`, by module-attribute lookup at call time with no caching, because the frozen `ec3_the_builder_applies_its_own_probes_per_policy` node and `_ForcedProbes` patch exactly those names. New tests use `probes`. Renaming any of the three leaves (for example in EXECFIND) needs a post-closeout SL-0 repair. A context built with injected `probes` counts as non-production evidence, like a replaced `deliver_seat_prompt`, and `invoke_board` refuses it on a landing call with `panel_probes_injected`, launching no seat;
      - it is rebuilt on every re-gate;
      - it is the only source of contexts, and a context is trusted for its content, not only its identity (item 8). On a landing call, `invoke_board` refuses with `panel_context_unverified`, before policy validation and with no seat launched, unless both checks below pass. Together they refuse hand-built contexts, `dataclasses.replace` copies, contexts mutated in place, and forged or mutated snapshots, including one passed through the builder. The mechanism adds no constructor field, so the five-field lists above stay as they are.
        - **Two reads of the user file.**
          - The *pre-seat* read is used for provenance. If its digest differs from `snapshot.user_digest`, the file changed during the run, and the result is the mid-run refusal `panel_user_file_changed`: the landing is refused and no seat launches. If the digest is equal, the user-side `[panel.*]` table parsed from those bytes must equal `snapshot.user_table`, and must equal the context's resolved table wherever that table's source is `user`. Otherwise the result is `panel_context_unverified`.
          - The *evaluation* read is a second read and hash, taken when `invoke_board` calls `evaluate_landing`. It supplies `user_digest_now`, so an edit made while the seats or the president run is refused as well.
          - Each entry surfaces `panel_user_file_changed` in the shape it already uses for a refused landing, and never as an escaping exception: `governed_board_gate` returns `promoted=False`, the runner writes no landing record or raises a typed refusal, run-train does not merge, and `advisor-board` exits non-zero. The frozen nodes pin only "not landed". `ec3e_user_file_edit_before_the_gate_is_refused` edits after the snapshot, and the pre-seat read catches it. `ec3e_user_file_edit_after_the_gate_is_refused` edits at the first seat launch, and the evaluation read catches it.
        - **Identity plus a content digest for what cannot be recomputed**, checked before the seats and again at evaluation. `snapshot_panel_run` and `build_panel_context` record each object they return in a module-private registry: its identity, plus a digest of its canonical content. For a snapshot that is every field; for a context it is every field, including `composed.board` and `seat_lenses`, and whether `probes` was injected. `invoke_board` recomputes the digest and requires the registered one. The builder refuses (`BoardConfigError`) a snapshot that is unregistered or whose digest no longer matches. `panel_context_unverified` is reserved for a registry failure, or for a table mismatch at an equal digest. Recomputation is impossible here for two reasons. First, in the direct-invoke nodes the sanctioned control replaces `repo_dir` with a private scratch directory, and the context holds no repository handle, so `invoke_board` cannot re-read the base-revision table. Second, the corpus injects hand-built `ExplicitProfileSeats` through `snapshot_panel_run(user_profile=)` and `build_panel_context(repository_profile=)`. The merge-time re-gate (SL-1, item 7) re-reads the repository half at a freshly fetched head.
        - A pass-through wrapper that returns the builder's own, unmodified object is accepted, as the ec3e harness requires.
        - Merge authority is `invoke_board`'s landing decision alone. A direct `evaluate_landing` call is not merge authority, for example one made with a forged context and a policy derived from that context.
  - `advisor_board.presets.BUILTIN_LENS_TEXT`.
  - `advisor_board.composition.compose_panel_board(table, *, is_available, auth_ok, preflight) -> ComposedPanel(board, seat_lenses, fallback_lanes, unfilled_lanes)`. `seat_lenses` is the only lens source.
  - `panel_invoker`:
    - `panel_landing_policy(tier, *, context) -> ReviewLandingPolicy`;
    - `ReviewLandingPolicy` gains additive `min_distinct_vendors: int | None = None` and `min_usable_seats: int = 0`. The defaults keep today's rule for every tier; `panel_landing_policy` sets the floor to 2 for `plan` and `production_code` only;
    - `evaluate_landing(policy, *, usable_legs, president_ruling, context, user_digest_now) -> LandingDecision`, the one evaluator. `invoke_board` calls it. It holds the policy-equals-context rule itself: a `policy` equal to `panel_landing_policy(tier, context=context)` for no tier gives `admitted=False`. A direct call with `review_policy_for_tier("plan")` or `review_policy_for_tier("production_code")` therefore cannot reintroduce the floor-0 fallback, because that policy equals no context's policy (the corpus's IF assumption). The policy carries no tier, so `invoke_board`'s tier-keyed equality check stays the binding one;
    - `invoke_board(..., panel_context: PanelContext | None = None, target_branch: str | None = None, reviewed_head: str | None = None, reviewed_pr: int | None = None)`. A `plan` or `production_code` landing without a context is refused with `panel_context_required`. `target_branch`, `reviewed_head` and `reviewed_pr: int | None = None` are cross-checks against the bindings the runtime reads itself (item 7). Without them a decision is not merge-capable;
    - maintainer decision on agent-harness#1094 items 6 and 11 (2026-09-27), verbatim: "When `invoke_board` receives a panel context without a `review_policy`, it must raise a typed error (panel context supplied without a review policy) and launch no seat. It must never fall back to `review_policy_for_tier(tier)`, because that policy has a floor of 0." The error is `PresidentPolicyError` with code `panel_review_policy_required`, raised before policy validation. Maintainer decision (2026-09-27, agent-harness#1111): the rule applies only to merge-approving (landing) calls, meaning calls where `landing_tier` is set, at every tier. A non-landing `advisor-board` run with a context and no policy keeps working, as the frozen `ec3e_non_landing_advisor_board_seats_only_its_task_lanes_and_labels_them` node requires. A call is landing if and only if `landing_tier is not None`, so a falsy tier (`""`, `0`, `False`) can never slip out of the rule as non-landing. Instead it is rejected outright by `_coerce_review_landing_tier` with `review_landing_tier_unknown`, before policy validation and with no seat launched. This matches today's `landing_tier is not None` checks and the sanctioned control's. `invoke_board` coerces the tier first. Aligning the sanctioned control: `harden_tdd_guard.py` is in HARDEN's `FROZEN_SL0_PATHS`. HARDEN's evidence verifier fails with "frozen test changed after reviewed SL-0" unless the file is byte-identical from HARDEN's reviewed SL-0 through its canonical-main record, and HARDEN's completion seal (its SL-6) is not yet recorded. So SL-1 does not edit the file. The alignment lives instead in SL-1's own `test_panel_sl1_contracts.py`, as a strict wrapper around `invoke_sanctioned_review_transport`. It coerces the tier first, so a falsy or unknown tier expects `review_landing_tier_unknown`. For a valid tier with a context and no `review_policy`, it expects `panel_review_policy_required` with zero calls to `_validate_review_board_policy` (spied, as the corpus's `_supply` does) and zero spawns, and so never accepts a `review_policy_for_tier` expectation. The guard's own default can be edited only after HARDEN's seal is recorded; agent-harness#1113 tracks that. No frozen PANEL node reaches that default: `_landing_kwargs` always supplies the policy when there is a context, the `panel_context_required` nodes pass no context, the non-landing node passes no tier, and the ec3e nodes assert that the entry passes its own policy;
    - leg naming: with several seats per vendor, `spawn`'s `leg` argument and `PanelLegResult.leg` stay the bare harness name. Seat identity travels only on `PanelLegResult.seat_key`, on `deliver_seat_prompt`'s `seat_key` and on `NativeAgentLegRequest.seat_key`. The corpus assumes this: its fake spawns key on the harness name, and `usable_distinct_vendors` is counted over `{leg.leg}`;
    - `PanelLabels`, carried on `PanelResult`, the `advisor-board` JSON and landing records;
    - `_seat_instructions(base, lens) -> tuple[str, str]`, which reads `context.composed.seat_lenses[<seat key>]`. The label is `prompt` iff a non-empty section was appended;
    - `deliver_seat_prompt(seat_key: str, route: str, prompt: str, send: Callable[[str], tuple[str, str]]) -> tuple[str, str]`, a module attribute looked up at call time whose default returns `send(prompt)`. On the brokered and TUI routes production calls it exactly once per seat per delivery attempt of an `invoke_board` run (a relaunch happens inside `send` with the same prompt, or calls it again as a new attempt; the president call does not use it), with that seat's `Seat.seat_key`, `route` in `{"brokered", "tui"}`, and the exact prompt it then hands to that seat's transport, after assembly and before that attempt's transport; its return is the seat's `(status, text)`. Replacing it changes neither the route nor the assembly: it marks that leg's result as non-production evidence (as `_has_injected_review_execution_seam` does) without switching away from the broker route. It is the observation seam that binds each frame to its seat for EC-PANEL-6 (agent-harness#1094).
- [ ] IF-0-PANEL-2 — `advisor_board.lens_frame.render_lens_section(lens: ResolvedLens) -> str` (slice 2). Its last line is `PRECEDENCE_STATEMENT`, byte-for-byte: `The verdict protocol above takes precedence over this lens wherever they conflict.` Nothing follows it.

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
| SL-0.5 | verify | SL-0.4 | `.phase-loop/evidence/PANEL/**` | receipt verifies | `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py verify --receipt-only` |

Rules for the frozen corpus:
- **Readiness keys.** A node skips in ordinary runs only while its slice's symbol is absent:
  - `ec1_*`–`ec5_*` and `ec3e_*` key on `resolve_panel_table`;
  - `ec6h_*` keys on `_seat_instructions` and `deliver_seat_prompt`, which SL-1 lands together;
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
- **`ec6_*` and `ec6h_*` bind each delivery to its seat by an identity production supplies, not by frame content**, so a swap of two seats' lenses fails them:
  - brokered and TUI: through `deliver_seat_prompt` -- one delivery per seat per attempt, on its lane's route, each seat's own lens inside its own digest-bound instructions frame;
  - native fill: through the native request's own `seat_key` and `instructions` fields (`NativeAgentLegRequest`, pre-existing) -- one request per native-filled seat per attempt, its `seat_key` being the `Seat.seat_key` that keys `context.composed.seat_lenses`, and `seat_lenses[seat_key]` (never the request's own `lens` metadata) inside its instruction channel; no frame is required there (EC-PANEL-6).
- **Receipt and suite gates.** SL-0.5 runs `verify --receipt-only`; bare `verify`, which also requires every node to pass, is the phase suite's gate.
- **Known receipt gap (agent-harness#1094 item 3).** The receipt's `red_environment` records only `PHASE_LOOP_TDD_EXPECT_GOVLEAN`, because the shared `content_tdd_receipt.v1` writer in `tdd_receipts.py` hard-codes it. The gap stays documented rather than fixed in PANEL: `tdd_receipts.py` belongs to GOVLEAN and the adapter's freeze scope excludes it, and a schema change would force re-recording the frozen receipt, which restarts SL-0. The adapter has no replay subcommand. `record-red` writes a new receipt into the frozen evidence paths, so it must never be used to replay. `verify` runs at HEAD, and `verify --receipt-only` runs nothing. Replay by hand, in scratch:
  - Run `git worktree add --detach <scratch> <base_commit>`. The receipt's `base_commit` is its `landing_commit`: the SL-0 commit itself, which already contains the frozen tests, the adapter and the golden, so no overlay is needed.
  - From that worktree's root (the argv's paths are repo-relative), run `red_argv` with `PHASE_LOOP_TDD_EXPECT_PANEL=1` and `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests`. This is the environment the recorder gave its pytest child. SL-0.4's command sets `PYTHONPATH=phase-loop-runtime/src` for the adapter process only, and the adapter's `_activated_env` extends it to `src:tests` for the child. The recorder also inherits the caller's environment and sets `PHASE_LOOP_TDD_EXPECT_GOVLEAN=1`, which is harmless.
  - Compare per-node outcomes with the recorded ones, not log bytes. At recording, `scan_red_run` required every node in `red_nodeids` to fail, and none to be skipped or to error. In this receipt `red_argv[0]` is a bare `python3`, so it resolves on the replaying machine. The collected node set must equal `red_nodeids` exactly, and the replay records the interpreter and pytest versions.

  The recorded command run without the PANEL flag skips every node and exits 0, so it is not a replay. GOVLEAN follow-up: agent-harness#1112 asks for an additive per-phase EXPECT field for future receipts, which would not re-record PANEL's.
- **One group per falsifier.** Each EC-PANEL-N falsifier in the roadmap gets its own node group. A later test correction restarts SL-0.

### SL-1 — Slice 1: lane tables, composition, landing minimum, labels

- **Scope**: Implement IF-0-PANEL-1 and make SL-0's `ec1_*`–`ec5_*` nodes green.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/config.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/presets.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/fixtures/advisor-boards.example.toml`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/tests/test_advisor_board_config.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_advisor_board_presets.py`, `phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py`, `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_train_review_monitoring_policy.py`, `phase-loop-runtime/tests/test_president_heartbeat_1001.py`, `phase-loop-runtime/tests/test_review_monitor_policy.py`, `phase-loop-runtime/tests/test_panel_sl1_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/merge_guard.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`
- **Interfaces provided**: IF-0-PANEL-1.
- **Interfaces consumed**: SL-0's frozen falsifiers and golden; `_reject_unknown`, `repo_board_config_path` and the `[president]` loader in `config.py` (pre-existing); `PanelResult.usable_legs` (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.0 | verify | — | none (a throwaway stub that never lands) | the SL-1 entry gates below | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k ec3e` |
| SL-1.1 | test | SL-1.0 | the eight existing test files above, `test_panel_sl1_contracts.py` | only assertions that pin the frozen `heartbeat_only` board, `LENS_CYCLE` backfill, "a missing vendor fails its seat", or composition refusing below `FLOOR_SEATS` change, and each change is listed in the landing record; the SL-1 falsifiers below are written red first | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_review_monitor_policy.py phase-loop-runtime/tests/test_panel_sl1_contracts.py` |
| SL-1.2 | impl | SL-1.1 | `config.py`, `presets.py`, `fixtures/advisor-boards.example.toml` | — | — |
| SL-1.3 | impl | SL-1.2 | `composition.py`, `panel_invoker.py`, `runner.py`, `train_runner.py` | early label run (below) | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k "ec3e_landing_labels_match_the_configuration_and_seat_outcomes and (runner or run_train)"` |
| SL-1.4 | impl | SL-1.3 | `governed_review.py`, `cli.py`, `CONTRACTS.md` | — | — |
| SL-1.5 | verify | SL-1.4 | all of the above | `ec1_*`–`ec5_*`, `ec3e_*`, `ec6h_*` plus the owned suites | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_panel_sl1_contracts.py phase-loop-runtime/tests/test_president_ladder_config.py phase-loop-runtime/tests/test_advisor_board_config.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_advisor_board_presets.py phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py phase-loop-runtime/tests/test_president_wiring.py phase-loop-runtime/tests/test_train_review_monitoring_policy.py phase-loop-runtime/tests/test_president_heartbeat_1001.py phase-loop-runtime/tests/test_review_monitor_policy.py` |

Task detail (files and seams only; the behaviour is EC-PANEL-1..5 and IF-0-PANEL-1):
- **SL-1.2** — `config.py`: the `[panel.*]` loader, snapshot, context builder, change validation and re-gate check. `[president]` is untouched. `presets.py`: `BUILTIN_LENS_TEXT` and the built-in tables.
- **SL-1.3** — `composition.py`: `compose_panel_board`. `compose_review_board` is unchanged and serves only the import-time snapshots. `panel_invoker.py`: the policy, the evaluator, labels, the context refusal and the hook. The entry points (`runner.py`, `train_runner.py`) snapshot at run start, build the context at their gate, and pass it.
- **SL-1.4** — `governed_review.py` and `cli.py` do the same: they snapshot at run start, build at their gate, and rebuild the context on re-gate. Neither module merges, so the merge-time check belongs to the merging components below. N1–N3 carry over as the roadmap states. Declared lens names follow EC-PANEL-1 with no prefix rule; N4 is covered by the fallback and SL-3's recovery docs.
- **Re-gate at merge (agent-harness#1094 item 7).** Two separate things:
  - the merge sites are closed by construction, through an authority token;
  - a source scan acts as a regression tripwire.

  Maintainer decision (2026-09-27, agent-harness#1111): the gateway scan is a regression tripwire, not a security boundary. The runtime is trusted, code-reviewed code, and a source scan cannot provably catch deliberate obfuscation.
  1. **An authority token, bound to what it approved.** `merge_guard.guarded_merge(repo_dir, *, authority, action)` lives in a new module owned by SL-1. `authority` is either the admitted `LandingDecision` that `invoke_board` returned, or a `NoLandingToken`. It is never `None` and never a bare context.
     - **Registration.** When it admits a landing, `invoke_board` registers the decision by identity plus a content digest, in the same module-private registry as contexts (no constructor field is added). The registry entry binds:
       - the tier;
       - the registered context the decision evaluated;
       - the repository identity: the repository's canonical root (`git rev-parse --show-toplevel`) and its `origin` URL, both read by the runtime;
       - for a PR landing, the PR's live `number`, `baseRefName`, `headRefOid`, `headRepository` and `url`, read by the runtime at decision time with `gh pr view <pr> --repo <origin owner/name> --json number,baseRefName,headRefOid,headRepository,url`;
       - for a push landing, the target branch and the reviewed head.

       The entry passes three new additive keywords to `invoke_board`: `target_branch`, `reviewed_head`, and for a PR landing `reviewed_pr`. They are cross-checks only. Each must equal the value the runtime read, or the decision is not merge-capable. A decision admitted without them is not merge-capable either, which is why the frozen direct-invoke nodes, which never merge, are unaffected. The registry holds strong references, so a collected object's `id()` cannot be reused. A governed closeout gets its decision from the `invoke_board` call that its own `_governed_premerge_review` makes, and `_perform_phase_closeout_impl` passes that decision to its push.
     - **Checks on each call.** `guarded_merge` does the following, in order, and refuses at the first failure:
       - re-verifies the decision's and the context's registrations;
       - requires the action's repository, target branch, head and (for a PR) PR number to equal the decision's bindings exactly;
       - looks up the target's branch rules (see 3) and refuses a queue-protected or unreadable target;
       - fetches the target and records its head as B0 (a failed fetch refuses). It requires the context's `gated_revision` to be an ancestor of B0;
       - calls `panel_regate_required(repo_dir, gated_revision=<the context's gated_revision>, target_head=B0)`. It refuses if the call returns `True` or raises;
       - re-hashes the user file, and refuses on any mismatch with the context's `snapshot.user_digest`;
       - for `GhPrMerge`, re-reads the PR's live `number`, `baseRefName`, `headRefOid` and base repository immediately before the attempt. It requires each to equal the binding, and refuses with zero attempts otherwise;
       - performs the action. `GhPrMerge` runs `gh pr merge <bound number> --repo <bound owner/name> --merge --match-head-commit <bound headRefOid>`, and takes nothing from the action except the decision reference.

       A decision that was refused once is retired, and a decision that merged is consumed.
     - **`NoLandingToken`.** Only `merge_guard.mint_no_landing_token()` may construct one, and only from the autonomous entry. The module keeps a runtime registry of the tokens it minted. The wrapper refuses the token if the run mode resolves to `governed`, if the run mode is unreadable, or if any landing decision was registered for this repository in the process. On this path the wrapper performs today's primitive byte-for-byte.
     - **Resume in a fresh process.** A governed run resumed in a fresh process has no registered decision. It refuses with `panel_merge_authority_missing`, and the board runs again.
  2. **Remote mutations live in named functions of `merge_guard.py`.** Each remote-mutating command sits in the body of exactly one function:
     - `guarded_merge`: `gh pr merge --merge --match-head-commit`, and the leased push to the target.
     - `publish_nontarget` takes no target from its caller. It resolves the protected destinations itself: the remote's default branch, every branch that reports as protected under classic branch protection or matches a ruleset, and the landing targets that the run-train roadmap and the phase-loop configuration declare. A failed lookup refuses. Everything it runs is checked against an allowlist grammar:
       - **Pushes.** It runs `git push <remote> <refspec>` with exactly ONE fully explicit refspec, `<src>:refs/heads/<name>`. `<src>` is a 40- or 64-hex SHA or `refs/heads/<local>`, and `<name>` is not protected. The only flags on its closed flag list are `--porcelain` and `--quiet`. Everything else is refused before any attempt, including:
         - no refspec, `HEAD`, `origin HEAD`, or an unqualified destination;
         - the matching refspecs `:` and `+:`;
         - `+` force;
         - deletions (`:<name>`, `--delete`, `-d`);
         - `--mirror`, `--all`, `--tags`, `--follow-tags`, `--set-upstream`/`-u`, `--push-option`/`-o`;
         - any other flag.
       - **GitHub operations.** It runs `gh pr create`, `gh pr comment`, `gh issue create|comment`, and `gh pr edit` with only `--title`, `--body`/`--body-file`, `--add-label`/`--remove-label` and `--add-reviewer`. `--base` is never allowed.
       - **`gh pr ready`, and any push to a PR's head branch.** These are refused unless all three hold, read live: auto-merge is off, the PR is not queued, and the PR's base is not queue-protected. Unreadable state refuses.

       Exact guarantee: the runtime never marks ready, retargets, or pushes to a PR whose live state shows auto-merge enabled, queue membership or a queue-protected base. It never pushes to a protected branch. What it does not govern is automation that GitHub or a human configures on an event, such as a merge bot reacting to `ready`; that is a non-boundary outside the runtime (below).
     - `dequeue`: the GraphQL `dequeuePullRequest` mutation, plus `gh pr merge --disable-auto`, confirmed by queue membership, as `train_runner._dequeue_pr` does today. `--disable-auto` alone cancels an auto-merge request; it does not remove a queued entry. `dequeue` needs no authority token because it can only remove: it takes a PR out of a queue and cancels auto-merge, and it cannot add, enable or merge. Its falsifier asserts that it never issues any other mutation.

     Later phases add remote mutations only as new named functions in this module, and add read-only commands only to `merge_guard.READ_ONLY_ALLOWLIST`. Those two are the module's extension seams (see Execution Notes).
  3. **Merge queue and base race.**
     - **Branch-rules lookup.** The up-front check covers both rulesets and classic branch protection. A failed or unreadable lookup refuses with `panel_merge_queue_unknown`.
     - **Merge queue.** Maintainer decision (2026-09-27, agent-harness#1111): refuse queue-protected targets up front (`panel_merge_queue_target`), and dequeue and refuse any attempt that comes back enqueued (`panel_merge_enqueued`). The re-gate inside the queue is deferred until a repository needs merge queues. Intended consequence: run-train no longer merges a panel landing into a queue-protected target. Residual: the queue can merge before the dequeue. A failed dequeue is the typed escalation `panel_merge_dequeue_failed`.
     - **Base race.** Maintainer decision (2026-09-27, agent-harness#1111): accept the window between the re-gate and GitHub's PR merge, as an explicit exception to EC-PANEL-1's re-gate rule. It applies only to that window, and only to `GhPrMerge`. After the merge, the wrapper compares the merge commit's first parent with B0. If they differ, or if the merge commit cannot be read, it raises the typed escalation `panel_merge_base_moved` for a human. Run-train records it in its result and ledger, and halts before the next node.
     - **Pushes.** `GitPush` requires the commit to descend from B0, and pushes with `--force-with-lease=refs/heads/<target>:<B0>`. That makes the push atomic against B0: a target that advances to B1 is refused, even if B1 is an ancestor of the commit.

  **The tripwire scan.** Its scope is exactly these forms:
  - the standard spawn APIs: `subprocess.*`, `os.exec*`, `os.spawn*`, `os.posix_spawn*`, `os.system`, `os.popen`, `pty.spawn` and `asyncio.create_subprocess_*`, called with a literal `git`/`gh` argv[0];
  - any list or tuple display whose first element is the literal `"git"` or `"gh"`, wherever it appears. This catches `argv = ["git", "push", …]` and a pass-through `_run([...])`;
  - `gh api` calls;
  - imports of a git library (GitPython, pygit2, dulwich) or a GitHub API client (PyGithub, ghapi, gidgethub);
  - HTTP through `urllib.request`, `http.client`, `requests`, `httpx` or `aiohttp` with a literal GitHub host and a non-`GET` or non-literal method.

  Everything else is a named residual below. The scope and the maintainer's residual list together partition the surface.

  Within that scope, it fails on anything it cannot classify. Outside `merge_guard.py`:
  - a `git` subcommand must be literal and on a closed list of local subcommands plus `fetch`/`ls-remote`/`clone`, and each subcommand's options must be on its own closed option list. That list never includes an exec-capable option: `-c`, `--exec-path`, `--exec`/`-x`, `foreach`, `bisect run`, `--upload-pack`/`-u`, `ext::` URLs, `grep -O`, `difftool --extcmd`, and the like. A `fetch` refspec destination must lie under `refs/remotes/`;
  - `gh` is limited to `pr view|list|checks|diff`, `issue view|list`, `auth status` and `repo view`;
  - `gh api` is checked against a closed flag allowlist: a literal path, `-H`/`--header`, `--jq`, `--paginate`, and `-X GET`/`--method GET` in either attached or separate spelling. Any other flag fails the scan, which catches `--field`, `--method=PUT` and `-XPUT`. `-f`/`-F` are illegal even alongside `-X GET`. The one exception is `gh api graphql -f query=<literal>`, whose literal body must be a `query`, never a `mutation`.

  **Named residuals** (the maintainer's list, exactly as decided). These are out of the scan's scope because the runtime is trusted and reviewed:
  - shell strings built at runtime, and `bash -c` payloads;
  - `curl` or `wget` calls to the API;
  - git aliases, and commands driven by config;
  - third-party spawn libraries;
  - non-literal HTTP, meaning a host that is not a literal. A literal GitHub host with a non-literal method is in scope, as stated above;
  - the data-driven spawn sites: the plan `suite_command` runner, and the harness session launch.

  **Non-boundaries outside the runtime.** These are not scan forms. The runtime cannot act on them, and they are listed for honesty:
  - manual merges by a human or an agent (including following a skill's prose, such as `skill-editor`'s `git push`);
  - an auto-merge a human enabled that GitHub itself fires;
  - repository automation triggered by a comment, a label or `ready`;
  - workflows that merge (`.github/workflows/**` is the CI boundary);
  - git hooks in the repository.

  **Today's merge sites**, each of which becomes a `guarded_merge` call:
  - `train_runner._live_merge_pr`;
  - `runner._perform_phase_closeout_impl`'s closeout push (`commit` and `manual` publish nothing);
  - `runner._run_legible_pr_transition`'s push to `refs/heads/main`.

  `governed_board_gate`'s `promoted` and the `advisor-board` landing JSON authorize no merge. SL-3.2 documents run-train and phase-loop as the merge paths.

  **Landing-path argv change.** The landing path adds the fetch, and the lease on pushes. SL-1.0 lists every test that drives a governed merge site, with its owning phase. Candidates today:
  - `test_train_merge.py` (RESIDUAL, INTEG, FAULTS, REVIEWTRUTH);
  - `test_train_invariants.py` (RESIDUAL and others);
  - `test_legible_review_repairs.py` (LEGIBLE, GOVLEAN);
  - `test_fab_activation_promotion.py` and `test_fab_delta_consumer.py` (FABREADMIT, RESIDUAL);
  - `test_fab_closeout_crash_safety.py` (RESIDUAL);
  - `test_train_prebuilt.py` (FABPUB).

  A needed change to a test SL-1 does not own routes to a plan amendment before any SL-1 production edit.
SL-1 entry gates (SL-1.0, before any production edit):
- **Receipt replay (item 3).** From the root of the scratch worktree (the argv paths are repo-relative), run the manual replay (SL-0 rules) once. It passes only if the per-node outcomes equal the recorded ones: every `red_nodeids` node fails, and none is skipped or errors. Any mismatch stops SL-1 and routes to an SL-0 repair. The comparison is attached to the SL-1 landing record.
- **Merge-surface inventory (item 7).** Run the gateway scan in report mode on the base. Every `git`/`gh` spawn outside the allowlist, and every test that drives a governed merge site, is listed with its module's owning phase. A site in a module SL-1 does not own routes to a plan amendment before any production edit.
- **Guard pass-through.** Confirm that `harden_tdd_guard` forwards an absent `review_policy` unchanged (it reads `call_kwargs.get("review_policy")` and substitutes nothing), so the strict wrapper can observe `panel_review_policy_required`. If it substitutes a policy, SL-1 stops, and the alignment routes to agent-harness#1113 with a plan amendment.
- **Harness dry-run (item 10).** Run the `ec3e_*` nodes against a throwaway stub of the IF-0-PANEL-1 names that never lands. The stub implements the identity registry, a `merge_guard` stub, and both user-file reads. The run therefore also proves that no harness layer, `harden_tdd_guard` included, copies a context. It also shows whether a frozen ec3e harness fakes `git`/`gh` for the merges or isolates `XDG_CONFIG_HOME` in a way that conflicts. Any such conflict routes to an SL-0 repair, and the frozen patch points (for example `_live_merge_pr`) are kept. Each node may pass or fail on an assertion about production behaviour, but none may error in the harness itself (an import, fixture or `TypeError` inside a `_Harness`, `_drive` or `_run_*` helper). A harness error stops SL-1 and routes to a post-closeout SL-0 repair (the agent-harness#614 precedent); the frozen node is never edited. pytest reports an exception raised in a helper as FAILED, not ERROR, so a result is classified by the frame that raised it. SL-1.0's output and stub, and SL-1.1's red run, go into the SL-1 landing record.
- **GOVSETUP shape (item 5).** Maintainer decision (2026-09-27, agent-harness#1111): the corpus's layout is accepted, and IF-0-GOVSETUP-1 must build on it. The layout is `.phase-loop/governance.toml`, `$XDG_CONFIG_HOME/agent-harness/governance.toml`, a `[tiers.<tier>] panel = [...]` table, and seat aliases. GOVSETUP's plan must conform to that layout (see IF-0-PANEL-1). The gate is met when `plans/manifest.json` has no committed GOVSETUP plan, or when that plan's IF-0-GOVSETUP-1 realizes the layout. A plan that does not conform is refused at its own review, and the corpus is not re-frozen. These nodes pin the layout: `ec1_target_head_panel_change_requires_a_regate`, `ec4_a_governance_profile_cannot_lower_the_minimum`, `ec4_every_seat_an_explicit_profile_names_is_required`, `ec4_repository_profile_takes_precedence_over_the_user_profile`, `ec5_labels_carry_the_explicit_profile_and_its_provenance`, `ec5_labels_carry_a_user_profile_path_and_digest_not_the_base`, `ec3e_target_head_profile_panel_list_change_after_the_gate_forces_a_regate` and `ec3e_a_profile_document_cannot_lower_the_minimum`.
- **Early real-serializer run (item 16).** As soon as SL-1.3 wires the runner and run-train entries, SL-1.3's command runs `ec3e_landing_labels_match_the_configuration_and_seat_outcomes` for those entries against the real label serializer, before SL-1.4. An assertion failure is SL-1's to fix. An error inside the frozen node's body routes to a post-closeout SL-0 repair, never an edit to the node. `--collect-only` confirms the selection is 4 nodes: `test_ec3e_landing_labels_match_the_configuration_and_seat_outcomes[runner-production_code-repository]`, `[runner-production_code-user]`, `[run_train-plan-repository]` and `[run_train-plan-user]`.

SL-1 falsifiers (`test_panel_sl1_contracts.py`, written red in SL-1.1; the `ec<N>` in each name is the EC-PANEL goal whose acceptance command selects it). SL-1.1 records the file's sha256 at its red run in the landing record, and the landed bytes must match it. A later correction re-runs SL-1.1 and records the new digest along with the reason. The `invoke_board` nodes go through `harden_tdd_guard.invoke_sanctioned_review_transport`, wrapped by the strict SL-1 wrapper above, as the frozen corpus does. That keeps HARDEN's fixture policy intact and observes a refusal's zero launches the same way. SL-1 edits files other phases claim, among them `advisor_board/backing.py` (HARDEN), `runner.py` and `train_runner.py`. `roadmap_ownership` will flag SL-1's landing, and its PR body carries a `Roadmap-Disposition:` trailer covering every Key-file claim that tool reports for SL-1's diff:
- `test_sl1_ec4_invoke_board_refuses_a_context_without_a_policy`: for every tier, a landing with a built context and no `review_policy` raises `panel_review_policy_required`, spawns zero seats and makes no policy validation (items 6 and 11);
- `test_sl1_ec4_a_falsy_landing_tier_is_rejected_not_treated_as_non_landing`: with a built context and no `review_policy`, a `landing_tier` of `""`, `0` or `False` raises `review_landing_tier_unknown`, spawns zero seats and makes no policy validation (items 6 and 11, agent-harness#1111);
- `test_sl1_ec4_an_untrusted_context_is_refused`: zero seats in every case (item 8). The first three cases are paired with their own matching `panel_landing_policy` and raise `panel_context_unverified`. In the two snapshot cases the builder raises `BoardConfigError`, so no context exists. It is parametrized over:
  - a hand-built context;
  - a `dataclasses.replace` copy with a lowered table;
  - the builder's own context, mutated in place;
  - a hand-built `PanelRunSnapshot` carrying a lowered table and the live user digest, passed through the builder;
  - a registered snapshot mutated before the build;
- `test_sl1_ec1_a_user_file_edit_during_the_run_is_refused`: parametrized over the edit's timing (after the first seat launches, and during the president call). The landing is refused at `invoke_board`, and at both non-merging landing entries (`governed_board_gate` and `advisor-board --landing-tier`) (B-A);
- `test_sl1_ec4_a_malformed_or_none_profile_fails_closed`: a malformed or unreadable profile, at base or in the user file, raises `BoardConfigError`. `none` is refused at `plan` and `production_code`, and at `tests_only` and `docs_only` it means no explicit seats (item 5);
- `test_sl1_ec4_evaluate_landing_refuses_a_policy_that_is_not_the_contexts`: `review_policy_for_tier(tier)` for `plan` and `production_code` gives `admitted=False`;
- `test_sl1_ec4_injected_probes_are_refused_on_a_landing`: `panel_probes_injected`, zero seats (item 12);
- `test_sl1_ec1_every_merge_site_refuses_before_any_attempt`: parametrized over every merge site. Each case asserts ZERO primitive invocations. The cases:
  - the decision or the context is absent on a governed landing;
  - the context is mutated after the decision;
  - the context is rebuilt and paired with the old decision;
  - the decision comes from a non-landing call, or from a refused landing;
  - a decision with no bound head or target;
  - a `NoLandingToken` on a landing path, or with an unreadable run mode;
  - a governed resume in a fresh process;
  - head substitution: an H2 that descends from B0 but is not the reviewed head;
  - repository substitution;
  - target substitution;
  - a PR retargeted after review (its live `baseRefName` changed);
  - PR substitution: a different PR number with a matching head SHA;
  - a mismatch between a caller cross-check keyword and the value the runtime read;
  - a `gated_revision` that is not an ancestor of B0;
  - `panel_regate_required` returning `True`: a `[panel.*]` change, or a change to only the profile `panel` list, and a retry after such a change;
  - `panel_regate_required` raising;
  - a failed fetch;
  - a user-file digest mismatch;
  - a queue-protected target (ruleset or classic protection), and an unreadable rules lookup.

  It also checks that the no-landing path's argv equals today's, byte-for-byte (item 7);
- `test_sl1_ec1_every_merge_site_handles_post_attempt_outcomes`: each case asserts exactly one attempt, then the typed refusal or escalation, then a halt:
  - an enqueued merge: one `gh pr merge`, then one `dequeue` call and its membership-confirmation read, then the refusal;
  - a failed dequeue escalates;
  - a lease rejection after the target advances to an ancestor-of-commit B1;
  - `panel_merge_base_moved`, for a moved base and for an unreadable merge commit, with run-train halting;
- `test_sl1_ec1_publish_nontarget_never_updates_a_protected_branch`: every case asserts zero push or mutation attempts. It is parametrized over:
  - `git push` with no refspec, `git push origin HEAD`, `:`, `+:`, `main`, `HEAD:main`, `+x:refs/heads/main`, `:main`, `--delete`, `--mirror`, `--all`, `--tags`, `--follow-tags`, `--set-upstream`, `-o`;
  - a caller that mis-declares its target;
  - a classic-protected branch, a ruleset branch, and a failed protection lookup;
  - `gh pr edit --base` on any PR, and any other `gh pr edit` flag off the list;
  - `gh pr ready`, and a push to a PR's head, when auto-merge is enabled, when the PR is queued, when its base is queue-protected, and when that state is unreadable;
- `test_sl1_ec1_dequeue_only_removes`: `dequeue` issues only `dequeuePullRequest`, `gh pr merge --disable-auto` and read-only confirmation calls;
- `test_sl1_ec1_gateway_tripwire` (required; a regression tripwire by the maintainer decision above): the scan described above, over `phase-loop-runtime/src/**` and `phase-loop-runtime/scripts/**`, `phase-loop-skills/**` and `skills-src/**` (Python, and shell scripts as literal command lines), and `install-agent-harness.sh`. Inside `merge_guard.py`, it also checks that each remote mutation sits in its one allowed function, and that `NoLandingToken` and `mint_no_landing_token` are referenced only at allowlisted sites. The self-falsifiers cover one case per in-scope form:
  - each spawn API;
  - a second function in `merge_guard.py`;
  - `gh api --field`;
  - `gh api --method=PUT`;
  - `gh api -XPUT`;
  - `gh api -X GET -f`;
  - a GraphQL mutation body;
  - `git push`;
  - `git send-pack`;
  - `git -c`;
  - `git rebase -x`;
  - `git submodule foreach`;
  - `git fetch --upload-pack`;
  - a `fetch` refspec that writes outside `refs/remotes/`;
  - a git library import;
  - a GitHub API client import;
  - a list display `["git", "push", …]` assigned to a variable and then spawned;
  - `requests.put` to a literal `api.github.com` URL;
  - `urllib.request.Request(..., method="PATCH")` to that host;
  - an `httpx`/`aiohttp` call whose method is non-literal;
  - a stray `NoLandingToken`.
- `test_sl1_ec3_build_panel_context_uses_the_injected_probes`: `probes` decides the seating without touching the three host leaves (item 12);
- `test_sl1_ec6_each_seat_is_bound_to_its_own_instruction_digest`: with `lens_frame` stubbed as in `ec6h_*`, two seats with different lenses, including a pair on the same harness, are both accepted by production digest binding. A swap of their instructions is refused (item 4).

### SL-2 — Slice 2: lens in each seat's instructions

- **Scope**: Implement IF-0-PANEL-2 and make SL-0's `ec6_*` nodes green (EC-PANEL-6).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/lens_frame.py`, `phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py`, `phase-loop-runtime/tests/test_train_review_packet.py`, `phase-loop-runtime/tests/test_panel_lens_transport.py`
- **Interfaces provided**: IF-0-PANEL-2.
- **Interfaces consumed**: IF-0-PANEL-1 (`ResolvedLens`, `_seat_instructions`, `ComposedPanel.seat_lenses`) from SL-1; the digest-bound frame builder in `panel_invoker.py` (pre-existing).
- **Parallel-safe**: no (consumes SL-1's hook; lands in one PR with SL-3).
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py`, `phase-loop-runtime/tests/test_train_review_packet.py`, `phase-loop-runtime/tests/test_panel_lens_transport.py` | update only assertions that pin identical seat instructions, and list each in the landing record; write the transport test red | `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py phase-loop-runtime/tests/test_train_review_packet.py phase-loop-runtime/tests/test_panel_lens_transport.py` |
| SL-2.2 | impl | SL-2.1 | `advisor_board/lens_frame.py` | — | — |
| SL-2.3 | verify | SL-2.2 | `advisor_board/lens_frame.py` | `ec6_*`, the transport test | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lens_delivery.py phase-loop-runtime/tests/test_panel_lens_transport.py phase-loop-runtime/tests/test_panel_tui_workspace_trust_223.py phase-loop-runtime/tests/test_train_review_packet.py` |

SL-2.2's `render_lens_section` renders the fixed heading `Review lens (subordinate to the verdict protocol)`, then the lens name and text verbatim, then exactly `The verdict protocol above takes precedence over this lens wherever they conflict.` (`PRECEDENCE_STATEMENT`), with nothing after it. Slice 2's board bundle includes SL-1's hook and the frame builder, because slice 2 changes every frame without touching `panel_invoker.py`.

**Item 4 (per-seat digest binding) is split across two lanes.**
- SL-1 owns the binding change, because it owns `panel_invoker.py`. Production today binds one instruction digest per review, and the broker checks every leg's staged instructions against it. SL-1 binds each seat's own instructions instead, by minting one authorization per distinct instruction set. This keeps the `ReviewIsolationAuthorization` / `public_board_review.v1` format that PRESROUTE and EXECFIND mint against. In `advisor_board/backing.py` it may change only that digest seam. A format change is out of scope and needs a plan amendment. `test_sl1_ec6_each_seat_is_bound_to_its_own_instruction_digest` proves the change with `lens_frame` stubbed.
- SL-2 owns the end-to-end acceptance test, `test_panel_lens_transport.py::test_ec6_distinct_seat_lenses_survive_digest_binding_and_transport`. It uses the real `lens_frame`, and faking only the child process, it drives distinct seat lenses through production digest binding on the brokered and TUI routes and through the native-fill request. It then checks, after transport, the instructions each seat actually received: the staged instructions its broker leg hands the child, the TUI session's input, and the native request's `instructions`. Each seat's received bytes must carry its own lens and pass its own digest check. The test includes two seats on the same harness. It binds each child's received bytes to its seat through production identity (the seat's own authorization, or `seat_key`), never through the leg name or the content, and a swap mutation between the two seats must fail it. The item-9 observation seam (`deliver_seat_prompt`) sits before transport and does not satisfy this test. A binding defect found here reopens SL-1.

### SL-3 — Documentation and phase reducer (lands with SL-2)

- **Scope**: EC-PANEL-7's documentation and entry-doc coverage, and the phase reduction.
- **Owned files**: `docs/advisor-board-capabilities-card.md`, `docs/TEAM-ONBOARDING.md`, `phase-loop-runtime/src/phase_loop_runtime/entry_doc_check.py`, `phase-loop-runtime/tests/test_entry_doc_check.py`, `.github/entry-doc-suppressions.json`, `.github/workflows/test.yml`, `CHANGELOG.md`, `.claude/docs-catalog.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal reducer).
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | docs | — | `.claude/docs-catalog.json` | — | `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if absent, record "docs-catalog rescan helper unavailable; manual catalog audit" |
| SL-3.2 | docs | SL-3.1 | the two docs, `entry_doc_check.py`, `test_entry_doc_check.py`, `.github/entry-doc-suppressions.json`, `.github/workflows/test.yml`, `CHANGELOG.md` | `ec7_*` | `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_doc_contract.py phase-loop-runtime/tests/test_entry_doc_check.py` |
| SL-3.3 | verify | SL-3.2 | — | — | `git diff --exit-code origin/main -- specs/phase-plans-v10.md` |

SL-3.2 documents lane tables, lens declarations, the fallback, the minimum and its precedence, and the labels (EC-PANEL-7). It also covers:
- the `[president]` pointer for a single-vendor user;
- out-of-band recovery for an operator with fewer than four vendors when a base table goes invalid (N4);
- that a minimum of 1 means one distinct *vendor*, not one seat;
- that run-train and phase-loop are the only merge paths, and that the `advisor-board` landing JSON authorizes no merge;
- the merge-guard refusal and escalation codes, with a human runbook for `panel_merge_base_moved` and `panel_merge_dequeue_failed`;
- recovery from a malformed base `.phase-loop/governance.toml`. Every panel landing reads that file at base, so a repair PR through a panel path is itself refused. The repair lands through the same out-of-band maintainer route as N4.

It makes the entry-doc check cover those sections in both documents (adding the capabilities card to `entry_doc_check.ENTRY_DOCS`), and touches `.github/entry-doc-suppressions.json` only if a suppression must change. At closeout it sets `PHASE_LOOP_TDD_EXPECT_PANEL=1` in `.github/workflows/test.yml`, so a later rename of a readiness symbol fails CI instead of silently skipping.

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
  - From SL-1's landing, `test_sl1_ec1_gateway_tripwire` binds every later phase that spawns `git`/`gh` or mutates a remote, for example RESIDUAL lane A's publish identity, FAB*, INTEG, RELEASE and the skills. Such a phase adds its mutation as a new named function in `merge_guard.py` (the module's extension seam), and adds its read-only commands to the allowlist in its own plan.
- **Readings of earlier criteria** (from the president ruling on agent-harness#1079):
  - EC-GOVLEAN-5's "full board" is the board EC-PANEL-4 requires.
  - EC-GOVSETUP-4's "four seats" is today's four named seats (`min_distinct_vendors=None`), labelled as an effective minimum of 4 from the built-in source. Take GOVSETUP's no-profile golden after SL-1.
- **Touch-shape falsifier (named seams).** `panel_invoker.py`, `governed_review.py`, `cli.py`, `runner.py`, `train_runner.py` and `advisor_board/backing.py` are shared with HARDEN, REVIEWTRUTH, LEGLIFE, LEGIBLE, FABPUB and RESIDUAL, and in-flight EXECFIND work touches `governed_review.py`/`panel_invoker.py`. A landing whose diff rewrites an existing line of these files outside its named seams fails the phase. The named seams are:
  - in `invoke_board`: the policy call sites, the landing-evaluation site, `PanelResult` fields and the per-seat `effective_instructions` assignments (the hook only);
  - in each entry point (`runner.py`, `train_runner.py`, `governed_review.py`, `cli.py`): the board-selection line, the `invoke_board` call line, the run-start snapshot, the gate-time context build, the re-gate check, the label writers, and imports the switch leaves unused;
  - at each merge site: its replacement by a `guarded_merge` call; in the autonomous entry only, `mint_no_landing_token`; the `target_branch`, `reviewed_head` and `reviewed_pr` keywords on the entry's `invoke_board` call;
  - each remote-mutation site the SL-1.0 inventory lists in a shared file SL-1 owns (including `train_runner._dequeue_pr` and run-train's escalation handling): its replacement by the corresponding `guarded_merge`, `publish_nontarget` or `dequeue` call;
  - in `backing.py`: the instruction-digest binding seam only (item 4);
  - `tests/harden_tdd_guard.py` is not edited (see IF-0-PANEL-1): it is in HARDEN's `FROZEN_SL0_PATHS` until HARDEN's seal is recorded. The `Roadmap-Disposition:` trailer covers every Key-file claim `roadmap_ownership` reports for SL-1's diff, not only `backing.py`.

  Everything else is additive. Landings take their turn in manifest queue order among ready landings.
- **Single-writer files.**
  - SL-0: the three new test files, the snapshot golden, the adapter and the receipt.
  - SL-1: `config.py`, `composition.py`, `presets.py`, `CONTRACTS.md`, the example TOML, `governed_review.py`, `cli.py`, `runner.py`, `train_runner.py` and the eight existing test files it lists.
  - SL-1: `panel_invoker.py`, including the lens hook.
  - SL-1: `test_panel_sl1_contracts.py`, the new `merge_guard.py`, and the instruction-digest seam in HARDEN's `advisor_board/backing.py`.
  - SL-2: `advisor_board/lens_frame.py`, the two frame-reading tests and `test_panel_lens_transport.py`.
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
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/**`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/merge_guard.py`, `docs/advisor-board-capabilities-card.md`, `docs/TEAM-ONBOARDING.md`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-PANEL.md`, `plans/manifest.json`, `phase-loop-runtime/tests/test_panel_lanes.py`, `phase-loop-runtime/tests/test_panel_lens_delivery.py`, `phase-loop-runtime/tests/test_panel_doc_contract.py`, `phase-loop-runtime/tests/data/panel_code_review_snapshot.golden.json`, `.phase-loop/evidence/PANEL/content-tdd-receipt.json`
- redaction posture: `metadata_only`
- downstream handling: none

## Verification

Run after all lanes merge:

```bash
PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/tests/panel_content_tdd_adapter.py verify
PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_panel_lens_delivery.py phase-loop-runtime/tests/test_panel_doc_contract.py phase-loop-runtime/tests/test_panel_sl1_contracts.py phase-loop-runtime/tests/test_panel_lens_transport.py
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
- [ ] EC-PANEL-1 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_panel_sl1_contracts.py -k "ec1 or ec3e"`; falsified by a path-entered `[panel.*]` table in a temporary user file or git fixture repository that a listed falsifier rejects being accepted, or the reverse, or by an import-time snapshot differing from the base golden.
- [ ] EC-PANEL-2 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k ec2`; falsified by `compose_panel_board` seating anything other than the first eligible vendor, or mis-recording an unfilled lane, across a parametrized availability, auth and preflight matrix.
- [ ] EC-PANEL-3 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_panel_sl1_contracts.py -k ec3`; falsified by `advisor-board`, the governed gate or `run-train` composing a different board for the same configuration.
- [ ] EC-PANEL-4 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py phase-loop-runtime/tests/test_panel_sl1_contracts.py -k "ec4 or ec3e"`; falsified by any configured value 1–4 admitting a landing below it, refusing a qualifying one on panel composition, or dropping an explicit profile seat, at `invoke_board` or through any entry point.
- [ ] EC-PANEL-5 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lanes.py -k "ec5 or ec3e"`; falsified by a result or landing record lacking any label, or carrying one (profile path and provenance included) that disagrees with the resolved configuration or the seat outcomes.
- [ ] EC-PANEL-6 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_lens_delivery.py phase-loop-runtime/tests/test_panel_lens_transport.py phase-loop-runtime/tests/test_panel_sl1_contracts.py -k ec6` (every frozen node in `test_panel_lens_delivery.py` is named `ec6_*`, so the filter drops none); falsified by a seat's lens name or text outside its authoritative instructions on any route, protocol text differing between two seats, or a `prompt` label without an appended section.
- [ ] EC-PANEL-7 — proven by `PHASE_LOOP_TDD_EXPECT_PANEL=1 PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_panel_doc_contract.py`; falsified by an accepted key or emitted label that is undocumented, a documented key the loader refuses, a missing `[president]` pointer or recovery section, or the entry-doc check not covering the sections.
