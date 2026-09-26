---
phase_loop_plan_version: 1
phase: PRESROUTE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 124554d1ce4232b60c71e8fc71d3f4e334c6d63080f8d62f498cbed68d08eeae
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      python3 phase-loop-runtime/scripts/verify_presroute_historical_receipt.py --repo .;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_govlean_panel_policy.py
      phase-loop-runtime/tests/test_president_wiring.py;
      PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/check_model_id_sources.py;
      grep -q 'EXPIRED by Consiliency/agent-harness#' plans/decision-interim-president-ratification-20260904.md;
      PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md;
      PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.goal_coverage import check_goal_coverage; r=check_goal_coverage(repo=Path("."), plan=Path("plans/phase-plan-v10-PRESROUTE.md"), roadmap=Path("specs/phase-plans-v10.md")); assert not r.unreferenced_ids and not r.dangling_refs, r';
      uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime
---

# PRESROUTE: President Execution Route

## Context

PRESROUTE gives the president ladder a HARDEN-authorized execution operation so
`requires_president` landings rule autonomously, reorders the ladder by seat alias,
and expires the interim ratification note in the same landing. It closes the gap the
2026-09-04 decision note recorded (agent-harness#752): today
`president_adapter.build_president_invoke` answers every seated rung with
`president_execution_route_unavailable` (`president_adapter.py`), so every
`plan`/`production_code` landing fails closed and the four converged PRs the note
cites had no path to `main`.

Current shape this phase changes: `PRESIDENT_LADDER`
(`panel_invoker.py:495`) is in a superseded order and pins inline model ids rather than
registry-resolved aliases; EC-PRESROUTE-3 fixes the seat-alias order (that criterion is
its single source; this plan never restates the order or any model id) and requires each
alias to resolve through the frozen registry PIN with the `model-id-source:` marker on
every id site. `invoke_president`
(`panel_invoker.py:552`) already walks the tuple and descends only on a typed
`president_unavailable`. Review isolation is minted in `advisor_board/backing.py`
(`ReviewIsolationAuthorization` / `public_board_review.v1`, agent-harness#737); the president
operation mints its authorization the same way and binds it to the seam exactly as
`spawn` does. The president grammar (`FINDING <id>: BLOCKING|DEFERRED — <reason>`,
terminal `FORCING DECISION:`) is already parsed by `_valid_president_grammar`. ABDPRES in
`advisor_board/CONTRACTS.md` (line 421) documents the current `requires_president` seam;
the new operation extends it by the same amendment path.

This plan touches only PRESROUTE's roadmap Key files, edits no frozen surface, and adds no
`Depends on` edge to the roadmap (the maintainer's concurrency ruling settled that). It
does not implement EXECFIND, RATIFY or GOVSETUP, does not change review-leg isolation or
the review completion grammar, and does not rename the `sol` alias.

## Interface Freeze Gates

- [ ] IF-0-PRESROUTE-1 — the president operation. Frozen by SL-1 (Lane A) in
  `president_operation.py` + the new `advisor_board/CONTRACTS.md` section (ABDPRES-style
  amendment path), with a golden fixture `phase-loop-runtime/tests/data/president_ruling_v1.golden.json`
  landed by SL-0 so Lane B (SL-2) tests against a fixed base day 1; RATIFY extends the
  line grammar against it. Concrete freeze:
  - **Callable**: `run_president_operation(*, brief: str, findings: Sequence[str], authorization: PresidentIsolationAuthorization, invoke: Callable[[str, str], Mapping[str, str]], max_substantive_rounds: int) -> PresidentOperationResult`. `PresidentIsolationAuthorization` is the additive identity minted in `backing.py` (operation `public_board_president.v1`, `child_credentialless=True`, `child_network_egress=False`, `live_tree_exposed=False`). `PresidentOperationResult` carries `ruling: PresidentRuling` (existing dataclass), `authorization_identity: str`, `rung_index: int`, `brief_digest: str`, `findings_digest: str`.
  - **Completion grammar**: per-finding `FINDING <id>: BLOCKING|DEFERRED — <reason>` lines, terminal `FORCING DECISION: <decision>` (the grammar `_valid_president_grammar` already parses).
  - **`president.ruling.json` record shape** (`schema` = `"president.ruling.v1"`): `schema` (str), `authorization_identity` (str, `"public_board_president.v1"`), `rung_index` (int, 0-based ladder index of the ruling rung), `model_id` (str, the resolved registry PIN), `format_reask_count` (int), `brief_digest` (str, lowercase sha256 hex), `findings_digest` (str, lowercase sha256 hex), `forcing_decision` (str), `finding_rulings` (list of `{"id": str, "disposition": "BLOCKING"|"DEFERRED", "reason": str}`).
  - **Findings-digest canonicalization**: `findings_digest = hashlib.sha256("\n".join(findings).encode("utf-8")).hexdigest()` over the findings in the exact order passed to the president prompt (matching `_president_prompt`'s join); SHA-256, lowercase hex; findings-only.
  - **Brief-digest canonicalization**: `brief_digest = hashlib.sha256(brief.encode("utf-8")).hexdigest()` over the exact composed brief text bytes as sent in the native request, before any harness wrapping; SHA-256, lowercase hex. It is separate from `findings_digest`; the two digests together bind brief and findings as EC-PRESROUTE-2 requires.
  - **Native-fill composition**: the native request and the returned fill each carry `brief_digest` and `findings_digest`; at the durable resume/join point the fill is rejected unless both equal the request's (a different brief yields a different `brief_digest` even with findings unchanged), and a native president fill is refused under `heartbeat_only`.
  - **Freeze verification**: `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k ruling_record_matches_frozen_contract` builds a record, asserts its keys/types equal the golden fixture (which carries both `brief_digest` and `findings_digest`) and that each digest recomputes from its input. SL-1's new `advisor_board/CONTRACTS.md` section is the frozen artifact Lane B tests against; the SL-0 golden fixture is its executable falsifier. Consumed by SL-2 (Lane B) and RATIFY.

## Lane Index & Dependencies

SL-0 — Lane B tests-first stage (content-bound frozen corpus)
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no
SL-1 — President operation, authorization identity, adapter (Lane A)
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no
SL-2 — Lane B implementation stage: rung routes, native Fable fill, ladder reorder, note expiry
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no
SL-3 — Documentation and phase reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Lane B tests-first stage (content-bound frozen corpus)

- **Scope**: Lane B's first stage. Land and freeze the phase's falsifiers and the IF-0-PRESROUTE-1 golden fixture before any production edit, recording the content-bound receipt through the existing `content_tdd_receipt.v1` mechanism (`phase_loop_runtime.tdd_receipts`), re-verified byte-equal at merge; no commit-topology assertion is used. Lane B owns these tests per the roadmap; the freeze forbids Lane B's implementation stage (SL-2) from editing them, and Lane A (SL-1) consumes them.
- **Owned files**: `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_govlean_panel_policy.py`, `phase-loop-runtime/tests/presroute_content_tdd_adapter.py`, `phase-loop-runtime/tests/data/president_ruling_v1.golden.json`, `.phase-loop/evidence/PRESROUTE/content-tdd-receipt.json`, `.phase-loop/evidence/PRESROUTE/content-tdd-receipt.red.stdout.log`, `.phase-loop/evidence/PRESROUTE/content-tdd-receipt.red.stderr.log`
- **Interfaces provided**: frozen PRESROUTE falsifiers, the IF-0-PRESROUTE-1 golden fixture, a `content_tdd_receipt.v1` receipt, RED-anchored ladder/wiring/operation assertions.
- **Interfaces consumed**: the pre-implementation ladder, wiring and adapter behavior (pre-existing); `phase_loop_runtime.tdd_receipts` recorder/verifier (pre-existing).
- **Parallel-safe**: no (tests-first boundary; SL-1 and SL-2 consume its frozen bytes and never edit them).
- **Tasks**:
  - test: Rewrite the ladder assertion to expect the seat-alias order EC-PRESROUTE-3 fixes, each alias resolved through its registry PIN, assert the walk visits rungs in that order and descends only on typed `president_unavailable`, and assert `check_model_id_sources.py` reports every id site marked. Assert a seated rung now routes through `public_board_president.v1` (not `president_execution_route_unavailable`), that a ruling receipt carries the authorization identity, and that a `plan`/`production_code` landing carrying `requires_president=False` is refused with a typed reason. Add the `ruling_record_matches_frozen_contract` case that builds a `president.ruling.json` record and asserts its keys/types equal `phase-loop-runtime/tests/data/president_ruling_v1.golden.json` and that `findings_digest` recomputes from the findings (IF-0-PRESROUTE-1). Add a `brief_binding` node: a negative case rejecting unchanged findings paired with a changed brief (different `brief_digest`) at resume, and a positive control where the same brief and findings verify. Pin these `-k` node identifiers that later ECs select: in `test_president_wiring.py` — `operation`, `authorization`, `launch_provider`, `native_fable`, `heartbeat`, `brief_binding`, `ruling_record`, `findings_digest`, `ruling_record_matches_frozen_contract`; in `test_govlean_panel_policy.py` — `ladder`, `requires_president_false_refused`.
  - test: Add `presroute_content_tdd_adapter.py`, a bounded wrapper over `phase_loop_runtime.tdd_receipts` (mirroring `proofgate_content_tdd_adapter.py`): a `record-red` subcommand that runs the frozen tests under `PHASE_LOOP_TDD_EXPECT_PRESROUTE=1`, emitting the imported `RED_ANCHOR_MARKER` plus a distinct `PRESROUTE_RED::<case-id>` marker and exiting 1, and calls `record_content_tdd_receipt`; and a `verify` subcommand that calls `verify_content_tdd_receipt`. Do not edit `tdd_receipts.py`.
  - impl: Run `presroute_content_tdd_adapter.py record-red` to capture the RED stdout/stderr and each test file's sha256 into `.phase-loop/evidence/PRESROUTE/content-tdd-receipt.json` against the pre-implementation base; bind no commit SHA, count, or tree shape. Land these test paths, the adapter, the golden fixture, and the receipt tests-first before any SL-1/SL-2 production edit. A later test correction restarts SL-0.

### SL-1 — President operation, authorization identity, adapter (Lane A)

- **Scope**: Add the HARDEN-authorized `public_board_president.v1` operation, its authorization identity, and route a seated rung through it; freeze IF-0-PRESROUTE-1.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/president_operation.py`, `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- **Interfaces provided**: IF-0-PRESROUTE-1 (`public_board_president.v1`, `run_president_operation` callable, completion grammar, `president.ruling.json` shape matching the SL-0 golden); `PresidentIsolationAuthorization` minted like review isolation and bound to the seam like `spawn`.
- **Interfaces consumed**: frozen PRESROUTE falsifiers (SL-0), `ReviewIsolationAuthorization` mint pattern (pre-existing, agent-harness#737).
- **Parallel-safe**: no (SL-2 consumes its frozen interface).
- **Tasks**:
  - impl: In `president_operation.py`, define the operation with its own mode, brief, and completion grammar; mint its authorization the same way review isolation is minted for `spawn` (`child_credentialless=True`, `child_network_egress=False`, `live_tree_exposed=False`) and bind it to the seam exactly as `spawn` is. Add the additive identity in `backing.py` beside `public_board_review.v1` without editing the review authorization.
  - impl: In `president_adapter.py`, replace the seated-rung `president_execution_route_unavailable` branch so `president_adapter` routes a seated rung through the operation; keep every other refusal path unchanged and keep EC-HARDEN-5's refusal of a ruling routed through advisory or laundered through a review leg.
  - impl: Add the new `advisor_board/CONTRACTS.md` section for the operation by the same amendment path as ABDPRES; freeze the `president.ruling.json` record shape.

### SL-2 — Lane B implementation stage: rung routes, native Fable fill, ladder reorder, note expiry

- **Scope**: Give every rung a launchable route through the single launch site, fill Fable natively under Claude Code, reorder the ladder by seat alias, write the durable ruling record, and expire the interim note with a runtime refusal.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `plans/decision-interim-president-ratification-20260904.md`
- **Interfaces provided**: reordered `PRESIDENT_LADDER` (alias tuple + registry PINs), native-president CLI flag, `president.ruling.json` written to the review stream, runtime refusal of `requires_president=False` for `plan`/`production_code`.
- **Interfaces consumed**: IF-0-PRESROUTE-1 (SL-1), `launch_provider` single launch site (`panel_invoker.py:1940`, pre-existing), `load_native_leg_fills` seam family (`panel_invoker.py:4936`, pre-existing).
- **Parallel-safe**: no (consumes SL-1's frozen operation; serializes after HARDEN/REVIEWTRUTH/RESIDUAL shared-file landings per the concurrency ruling).
- **Tasks**:
  - impl: In `panel_invoker.py`, at the named ladder-tuple and alias sites only, set `PRESIDENT_LADDER` to the seat-alias tuple EC-PRESROUTE-3 fixes, each alias resolving to its vendor's frozen registry PIN with the `model-id-source:` marker; route each non-native rung to its vendor CLI via `launch_provider` and nowhere else per EC-PRESROUTE-2; add the native Fable seam (deferred fill with a durable resume/join point, refused under `heartbeat_only` as a native leg fill is); add the additive guard that refuses a `plan`/`production_code` landing carrying `requires_president=False` with a typed reason; write `PanelResult.president` and the per-finding rulings to the review stream as `president.ruling.json` in the frozen IF-0-PRESROUTE-1 shape.
  - impl: In `cli.py`, add the native-president flag that fills the Fable rung natively when the driving harness is Claude Code and through the self-PTY adapter elsewhere, mirroring the existing native-leg flags.
  - impl: In the decision note, append the final `EXPIRED by Consiliency/agent-harness#<its number>` row and mark the note closed; do not rewrite earlier rows.

### SL-3 — Documentation and phase reducer

- **Scope**: Refresh the docs catalog, update cross-cutting docs this phase touches, and reduce the phase. This phase amends no spec: its Spec Closeout decision is `no_spec_delta` and the roadmap is not PRESROUTE's to amend (a maintainer ruling / LEGIBLE owns roadmap edits).
- **Owned files**: `CHANGELOG.md`, `.claude/docs-catalog.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal reducer).
- **Tasks**:
  - docs: Rescan the docs catalog (`python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if absent, record "docs-catalog rescan helper unavailable; manual catalog audit" and proceed).
  - docs: Add the CHANGELOG note for the president operation, ladder reorder, native fill, and note expiry; record any catalog file intentionally skipped.
  - verify: Assert this phase touched no spec (`git diff --exit-code -- specs/phase-plans-v10.md`), then run repo doc linters if any are configured; else no-op.

## Execution Policy

- work-unit defaults: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-1: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-2: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-3: effort=`medium`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- **Binding ruling — governance supersession on PRESROUTE delivery** (agent-harness#935): from the merge to `main` of the PR that lands EC-PRESROUTE-3 and carries its phase-ledger row in the same PR, the availability ladder is the EC-PRESROUTE-3 order by seat alias; the ladder sentences of EC-GOVLEAN-5 and the 2026-08-12 supersession note become historical-descriptive from that event and are not rewritten. Until that event the GOVLEAN ladder keeps exclusive authority. Model ids are never restated in roadmap text; the registry and its `model-id-source:` markers are the only carrier.
- **Post-landing policy amendment** (agent-harness#1025): rung `fable` now resolves to Opus 5.5 first. The SL-0 receipt proves agent-harness#998's original frozen bytes; the later amendment changed that ladder test. The historical verifier checks the unchanged receipt and RED logs in agent-harness#998's landing checkout; current tests check the amended behavior. Do not claim a separate RED commit for agent-harness#1025.
- **Binding ruling — concurrency on PRESROUTE and EXECFIND** (agent-harness#935, maintainer 2026-09-21): the round-1 board question in the scope notes — whether the declared overlap with HARDEN, REVIEWTRUTH, LEGLIFE and RESIDUAL needs `Depends on` edges — is ratified in the negative. Declared overlap plus the touch-shape falsifier is sufficient; no edge is added and no phase is edited. The `HARDEN → PRESROUTE` edge is satisfied by the landed isolation-authorization mechanism (`advisor_board/backing.py`, `ReviewIsolationAuthorization` / `public_board_review.v1`, agent-harness#737), not by HARDEN's completion or EC-HARDEN-5. PRESROUTE may be planned and executed now, concurrently with HARDEN, REVIEWTRUTH and SCHED, by a lane other than the one holding those phases; its landings still serialize after the owning phases' landings on any shared file line both rewrite.
- **Touch-shape falsifier (named seams)**: `panel_invoker.py`, `advisor_board/backing.py` and `cli.py` are shared with the open HARDEN/REVIEWTRUTH/LEGLIFE/RESIDUAL phases. A landing PR of this phase whose diff deletes or rewrites an existing line of a shared owned file OUTSIDE its named seams fails the phase. Named seams where rewriting an existing line is authorized: in `panel_invoker.py`, the `PRESIDENT_LADDER` tuple and the ladder alias/id sites; in `backing.py`, additive identity only (no rewrite of the review authorization); in `cli.py`, additive flag registration only. Every other touch is additive (new modules, new keyword-only seams, new guard).
- **Lane B two stages (tests-first ownership)**: the roadmap decomposes into two lanes and assigns the two pinned tests to Lane B. Lane B runs in two stages: SL-0 is Lane B's tests-first stage (Lane B retains roadmap ownership of the tests, plus the receipt adapter, golden fixture, and receipt evidence it lands), and SL-2 is Lane B's implementation stage. EC-PRESROUTE-0's freeze forbids SL-2 from editing the SL-0 test bytes (re-verified byte-equal at merge), and Lane A (SL-1) consumes the frozen tests and golden. Splitting Lane B into a tests-first stage and an impl stage keeps Lane B's roadmap ownership of its tests while avoiding a Lane A↔Lane B cycle (Lane B's wiring test covers Lane A's `president_operation.py`, and SL-2 consumes Lane A's IF-0-PRESROUTE-1); an implementation lane owning tests does not require editing them after freeze.
- **Single-writer files**: `panel_invoker.py`, `cli.py`, decision note (SL-2 sole writer); `backing.py`, `CONTRACTS.md`, `president_operation.py`, `president_adapter.py` (SL-1 sole writer); the two test files, `presroute_content_tdd_adapter.py`, the golden fixture, and the receipt evidence (SL-0 sole writer); `CHANGELOG.md`, `.claude/docs-catalog.json` (SL-3 sole writer). No file is owned by two lanes.
- **Known destructive changes**: SL-2 rewrites the `PRESIDENT_LADDER` tuple lines and the ladder alias/id sites in `panel_invoker.py` (a named seam), and SL-1 replaces the seated-rung refusal branch in `president_adapter.py` (Lane A's own file). Both are authorized. No lane deletes a file another lane produces. `tdd_receipts.py` is not edited (SL-0 wraps it in a new adapter).
- **Expected add/add conflicts**: none — SL-0 stubs no source file that a later lane replaces.
- **SL-0 re-exports**: none — SL-0 owns only test files, the adapter, the golden fixture, and receipt evidence, and adds no package `__init__` symbol.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/president_operation.py`, `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `plans/decision-interim-president-ratification-20260904.md`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-PRESROUTE.md`, `plans/manifest.json`, `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_govlean_panel_policy.py`, `phase-loop-runtime/tests/data/president_ruling_v1.golden.json`, `.phase-loop/evidence/PRESROUTE/content-tdd-receipt.json`, `.phase-loop/runs/**/president.ruling.json`
- redaction posture: `metadata_only`
- downstream handling: none; roadmap bytes remain unchanged and RATIFY consumes IF-0-PRESROUTE-1

## Verification

Run after all lanes merge (the pytest commands are RED-first targets on base and expected to fail until the impl lands):

```bash
python3 phase-loop-runtime/scripts/verify_presroute_historical_receipt.py --repo .
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k ruling_record_matches_frozen_contract
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_govlean_panel_policy.py -k ladder
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py
PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/check_model_id_sources.py
grep -q 'EXPIRED by Consiliency/agent-harness#' plans/decision-interim-president-ratification-20260904.md
```

Plan-artifact checks (green on the plan branch now):

- `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-PRESROUTE.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; v=validate_manifest(Path("plans").joinpath("manifest.json")); assert v.valid, "; ".join(v.errors)'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.planner_validation import validate_plan_dispatch_hints; f=validate_plan_dispatch_hints(Path("plans").joinpath("phase-plan-v10-PRESROUTE.md").read_text()); assert not f, f'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.goal_coverage import check_goal_coverage; r=check_goal_coverage(repo=Path("."), plan=Path("plans/phase-plan-v10-PRESROUTE.md"), roadmap=Path("specs/phase-plans-v10.md")); assert not r.unreferenced_ids and not r.dangling_refs, r'`
- `python3 -c 'from pathlib import Path; assert len(Path("plans").joinpath("phase-plan-v10-PRESROUTE.md").read_text().split()) <= 3000'`
- `git diff --exit-code -- specs/phase-plans-v10.md`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-PRESROUTE-0 — proven by `python3 phase-loop-runtime/scripts/verify_presroute_historical_receipt.py --repo .`, which checks unchanged receipt and RED-log bytes against agent-harness#998 and runs the frozen adapter in that landing checkout; falsified by drift in those bytes, a changed frozen test at that landing, or missing RED evidence. Agent-harness#1025 later amended the ladder test; current green tests prove its behavior, while the original receipt remains historical.
- [ ] EC-PRESROUTE-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k "operation or authorization"`; falsified by a path-entered mutation leaving a seated rung at `president_execution_route_unavailable` or producing a ruling receipt lacking the president authorization identity.
- [ ] EC-PRESROUTE-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k "launch_provider or native_fable or heartbeat or brief_binding"`; falsified by a path-entered mutation letting a rung spawn outside `launch_provider`, a native president fill accepted under `heartbeat_only`, or a fill with unchanged findings but a changed brief (mismatched `brief_digest`) accepted at resume.
- [ ] EC-PRESROUTE-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_govlean_panel_policy.py -k ladder` and `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/check_model_id_sources.py`; falsified by a path-entered mutation making `PRESIDENT_LADDER` differ from the tuple EC-PRESROUTE-3 fixes or `check_model_id_sources.py` report an unmarked id.
- [ ] EC-PRESROUTE-4 — proven by `grep -q 'EXPIRED by Consiliency/agent-harness#' plans/decision-interim-president-ratification-20260904.md` and `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_govlean_panel_policy.py -k requires_president_false_refused`; falsified by a `plan`/`production_code` landing carrying `requires_president=False` succeeding or the note lacking the EXPIRED row.
- [ ] EC-PRESROUTE-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k "ruling_record or findings_digest"`; falsified by a path-entered mutation producing a ruling with no stream record or a record whose `findings_digest` differs from the prompt's findings.
