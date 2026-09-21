---
phase_loop_plan_version: 1
phase: PRESROUTE
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 19b9c36311c93d0534c4cab1187cfda59ee589ee2c904aa0b71b581d09daf87e
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_govlean_panel_policy.py
      phase-loop-runtime/tests/test_president_wiring.py;
      PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/check_model_id_sources.py;
      grep -q 'EXPIRED by Consiliency/agent-harness#' plans/decision-interim-president-ratification-20260904.md;
      PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md;
      PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli goal-coverage-audit --roadmap specs/phase-plans-v10.md --phase PRESROUTE --dry-run;
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
(`panel_invoker.py:495`) is `("fable", "sol", "grok-4.6", "gemini-3.8-flash")` — the
wrong order and inline model ids; EC-PRESROUTE-3 requires `("sol", "fable", "grok",
"gemini")` (Astra, Fable, Grok, Gemini) resolving through the frozen registry PIN, every
id site carrying the `model-id-source:` marker. `invoke_president`
(`panel_invoker.py:552`) already walks the tuple and descends only on a typed
`president_unavailable`. Review isolation is minted in `advisor_board/backing.py`
(`ReviewIsolationAuthorization` / `public_board_review.v1`, `child_credentialless=True`,
`child_network_egress=False`, `live_tree_exposed=False`, agent-harness#737); the president
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

- [ ] IF-0-PRESROUTE-1 — the president operation: identity `public_board_president.v1`,
  its completion grammar (`FINDING <id>: BLOCKING|DEFERRED — <reason>` lines, terminal
  `FORCING DECISION:`), and the `president.ruling.json` record shape (authorization
  identity, rung index, model id, format re-ask count, findings digest). Frozen by SL-1
  (Lane A) in `president_operation.py` + the new `advisor_board/CONTRACTS.md` section so
  RATIFY extends the line grammar against a fixed base. Consumed by SL-2 (Lane B).

## Lane Index & Dependencies

SL-0 — Tests-first frozen corpus (content-bound)
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no
SL-1 — President operation, authorization identity, adapter (Lane A)
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no
SL-2 — Rung routes, native Fable fill, ladder reorder, note expiry (Lane B)
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no
SL-3 — Documentation, spec reconciliation, phase reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Tests-first frozen corpus (content-bound)

- **Scope**: Land and freeze the phase's falsifiers before any production edit, with the EC-GOVLEAN-2 content-bound receipt (blob hashes plus RED output digest against the pre-implementation base), re-verified byte-equal at merge; no commit-topology assertion is used.
- **Owned files**: `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_govlean_panel_policy.py`
- **Interfaces provided**: frozen PRESROUTE falsifiers, content-bound receipt, RED-anchored ladder/wiring/operation assertions.
- **Interfaces consumed**: the pre-implementation ladder, wiring and adapter behavior (pre-existing).
- **Parallel-safe**: no (tests-first boundary; SL-1 and SL-2 consume its frozen bytes and never edit them).
- **Tasks**:
  - test: Rewrite the ladder assertion to expect `("sol", "fable", "grok", "gemini")` resolved through the registry PIN, assert the walk visits rungs in that order and descends only on typed `president_unavailable`, and assert `check_model_id_sources.py` reports every id site marked. Assert a seated rung now routes through `public_board_president.v1` (not `president_execution_route_unavailable`), that a ruling receipt carries the authorization identity, and that a `plan`/`production_code` landing carrying `requires_president=False` is refused with a typed reason.
  - test: Record raw RED output and blob hashes for each frozen test against the pre-implementation base as the content-bound receipt; bind no commit SHA, count, or tree shape.
  - impl: Land only these two test paths tests-first; obtain the receipt before any SL-1/SL-2 production edit. A later test correction restarts SL-0.

### SL-1 — President operation, authorization identity, adapter (Lane A)

- **Scope**: Add the HARDEN-authorized `public_board_president.v1` operation, its authorization identity, and route a seated rung through it; freeze IF-0-PRESROUTE-1.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/president_operation.py`, `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- **Interfaces provided**: IF-0-PRESROUTE-1 (`public_board_president.v1`, completion grammar, `president.ruling.json` shape); a president authorization minted like review isolation and bound to the seam like `spawn`.
- **Interfaces consumed**: frozen PRESROUTE falsifiers (SL-0), `ReviewIsolationAuthorization` mint pattern (pre-existing, agent-harness#737).
- **Parallel-safe**: no (SL-2 consumes its frozen interface).
- **Tasks**:
  - impl: In `president_operation.py`, define the operation with its own mode, brief, and completion grammar; mint its authorization the same way review isolation is minted for `spawn` (`child_credentialless=True`, `child_network_egress=False`, `live_tree_exposed=False`) and bind it to the seam exactly as `spawn` is. Add the additive identity in `backing.py` beside `public_board_review.v1` without editing the review authorization.
  - impl: In `president_adapter.py`, replace the seated-rung `president_execution_route_unavailable` branch so `president_adapter` routes a seated rung through the operation; keep every other refusal path unchanged and keep EC-HARDEN-5's refusal of a ruling routed through advisory or laundered through a review leg.
  - impl: Add the new `advisor_board/CONTRACTS.md` section for the operation by the same amendment path as ABDPRES; freeze the `president.ruling.json` record shape.

### SL-2 — Rung routes, native Fable fill, ladder reorder, note expiry (Lane B)

- **Scope**: Give every rung a launchable route through the single launch site, fill Fable natively under Claude Code, reorder the ladder by seat alias, write the durable ruling record, and expire the interim note with a runtime refusal.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `plans/decision-interim-president-ratification-20260904.md`
- **Interfaces provided**: reordered `PRESIDENT_LADDER` (alias tuple + registry PINs), native-president CLI flag, `president.ruling.json` written to the review stream, runtime refusal of `requires_president=False` for `plan`/`production_code`.
- **Interfaces consumed**: IF-0-PRESROUTE-1 (SL-1), `launch_provider` single launch site (`panel_invoker.py:1940`, pre-existing), `load_native_leg_fills` seam family (`panel_invoker.py:4936`, pre-existing).
- **Parallel-safe**: no (consumes SL-1's frozen operation; serializes after HARDEN/REVIEWTRUTH/RESIDUAL shared-file landings per the concurrency ruling).
- **Tasks**:
  - impl: In `panel_invoker.py`, at the named ladder-tuple and alias sites only, set `PRESIDENT_LADDER = ("sol", "fable", "grok", "gemini")` resolving each alias to its vendor's frozen registry PIN with the `model-id-source:` marker; route Astra through the codex CLI, Grok through the grok CLI, Gemini through `agy`, each via `launch_provider` and nowhere else; add the native Fable seam (deferred fill with a durable resume/join point, refused under `heartbeat_only` as a native leg fill is); add the additive guard that refuses a `plan`/`production_code` landing carrying `requires_president=False` with a typed reason; write `PanelResult.president` and the per-finding rulings to the review stream as `president.ruling.json`.
  - impl: In `cli.py`, add the native-president flag that fills the Fable rung natively when the driving harness is Claude Code and through the self-PTY adapter elsewhere, mirroring the existing native-leg flags.
  - impl: In the decision note, append the final `EXPIRED by Consiliency/agent-harness#<its number>` row and mark the note closed; do not rewrite earlier rows.

### SL-3 — Documentation, spec reconciliation, phase reducer

- **Scope**: Refresh the docs catalog, update cross-cutting docs this phase touches, append any empirically-wrong-freeze amendments, and reduce the phase.
- **Owned files**: `CHANGELOG.md`, `.claude/docs-catalog.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal reducer).
- **Tasks**:
  - docs: Rescan the docs catalog (`python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if absent, record "docs-catalog rescan helper unavailable; manual catalog audit" and proceed).
  - docs: Add the CHANGELOG note for the president operation, ladder reorder, native fill, and note expiry; record any catalog file intentionally skipped.
  - docs: Append `### Post-execution amendments` to the PRESROUTE spec section only if a freeze was empirically wrong this run; append-only, dated. Do not edit `specs/phase-plans-v10.md` otherwise.
  - verify: Run repo doc linters if any are configured; else no-op.

## Execution Policy

- work-unit defaults: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-1: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-2: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-3: effort=`medium`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- **Binding ruling — governance supersession on PRESROUTE delivery** (agent-harness#935): from the merge to `main` of the PR that lands EC-PRESROUTE-3 and carries its phase-ledger row in the same PR, the availability ladder is the EC-PRESROUTE-3 order by seat alias; the ladder sentences of EC-GOVLEAN-5 and the 2026-08-12 supersession note become historical-descriptive from that event and are not rewritten. Until that event the GOVLEAN ladder keeps exclusive authority. Model ids are never restated in roadmap text; the registry and its `model-id-source:` markers are the only carrier.
- **Binding ruling — concurrency on PRESROUTE and EXECFIND** (agent-harness#935, maintainer 2026-09-21): the round-1 board question in the scope notes — whether the declared overlap with HARDEN, REVIEWTRUTH, LEGLIFE and RESIDUAL needs `Depends on` edges — is ratified in the negative. Declared overlap plus the touch-shape falsifier is sufficient; no edge is added and no phase is edited. The `HARDEN → PRESROUTE` edge is satisfied by the landed isolation-authorization mechanism (`advisor_board/backing.py`, `ReviewIsolationAuthorization` / `public_board_review.v1`, agent-harness#737), not by HARDEN's completion or EC-HARDEN-5. PRESROUTE may be planned and executed now, concurrently with HARDEN, REVIEWTRUTH and SCHED, by a lane other than the one holding those phases; its landings still serialize after the owning phases' landings on any shared file line both rewrite.
- **Touch-shape falsifier (named seams)**: `panel_invoker.py`, `advisor_board/backing.py` and `cli.py` are shared with the open HARDEN/REVIEWTRUTH/LEGLIFE/RESIDUAL phases. A landing PR of this phase whose diff deletes or rewrites an existing line of a shared owned file OUTSIDE its named seams fails the phase. Named seams where rewriting an existing line is authorized: in `panel_invoker.py`, the `PRESIDENT_LADDER` tuple and the ladder alias/id sites; in `backing.py`, additive identity only (no rewrite of the review authorization); in `cli.py`, additive flag registration only. Every other touch is additive (new modules, new keyword-only seams, new guard).
- **Tests-first ownership reconciliation**: the scope note lists the two pinned tests under Lane B, and EC-PRESROUTE-0 requires the TEST LANE LANDED FIRST and re-verified byte-equal at merge. To satisfy both without a Lane A↔Lane B cycle (Lane B's wiring test covers Lane A's `president_operation.py`, while Lane B's impl consumes Lane A's IF-0-PRESROUTE-1), the two test files are owned by the tests-first lane SL-0, which lands and freezes them before either impl lane; SL-1 and SL-2 consume the frozen bytes and never edit them. This honors the scope note's intent (the tests are the wiring/ladder domain Lane B implements against) and the byte-equal-at-merge criterion, which an impl lane owning the tests would violate.
- **Single-writer files**: `panel_invoker.py`, `cli.py`, decision note (SL-2 sole writer); `backing.py`, `CONTRACTS.md`, `president_operation.py`, `president_adapter.py` (SL-1 sole writer); the two test files (SL-0 sole writer); `CHANGELOG.md`, `.claude/docs-catalog.json` (SL-3 sole writer). No file is owned by two lanes.
- **Known destructive changes**: SL-2 rewrites the `PRESIDENT_LADDER` tuple lines and the ladder alias/id sites in `panel_invoker.py` (a named seam), and SL-1 replaces the seated-rung refusal branch in `president_adapter.py` (Lane A's own file). Both are authorized. No lane deletes a file another lane produces.
- **Expected add/add conflicts**: none — SL-0 stubs no source file that a later lane replaces.
- **SL-0 re-exports**: none — SL-0 owns only test files and adds no package `__init__` symbol.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/president_operation.py`, `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `plans/decision-interim-president-ratification-20260904.md`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-PRESROUTE.md`, `plans/manifest.json`, `phase-loop-runtime/tests/test_president_wiring.py`, `phase-loop-runtime/tests/test_govlean_panel_policy.py`, `.phase-loop/runs/**/president.ruling.json`
- redaction posture: `metadata_only`
- downstream handling: none; roadmap bytes remain unchanged and RATIFY consumes IF-0-PRESROUTE-1

## Verification

Run after all lanes merge (the pytest commands are RED-first targets on base and expected to fail until the impl lands):

```bash
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
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli goal-coverage-audit --roadmap specs/phase-plans-v10.md --phase PRESROUTE --dry-run`
- `python3 -c 'from pathlib import Path; assert len(Path("plans").joinpath("phase-plan-v10-PRESROUTE.md").read_text().split()) <= 3000'`
- `git diff --exit-code -- specs/phase-plans-v10.md`
- `git diff --check`

## Acceptance Criteria

- [ ] EC-PRESROUTE-0 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py phase-loop-runtime/tests/test_govlean_panel_policy.py` collecting GREEN at merge against the recorded EC-GOVLEAN-2 content-bound receipt (blob hashes plus RED output digest on the pre-implementation base at `phase-loop-runtime/tests/test_president_wiring.py` and `phase-loop-runtime/tests/test_govlean_panel_policy.py`), re-verified byte-equal at merge; falsified by a path-entered one-byte mutation to either frozen test making its merge-time blob hash differ from its freeze-time record, by absent RED output for any module, or by any commit-topology assertion.
- [ ] EC-PRESROUTE-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k "operation or authorization"`; falsified by a seated rung still answering `president_execution_route_unavailable`, a ruling receipt with no president authorization identity, the review classifier accepting a `FORCING DECISION:` text as a review, or a ruling produced with child network egress or credentials.
- [ ] EC-PRESROUTE-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k "launch_provider or native_fable or heartbeat"`; falsified by a path-entered mutation at the launch site that lets a rung spawn outside `launch_provider`, obtains a Fable ruling by spawning a second Claude TUI under Claude Code, accepts a native president fill under `heartbeat_only`, or accepts a fill whose digests do not bind the brief and findings.
- [ ] EC-PRESROUTE-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_govlean_panel_policy.py -k ladder` and `PYTHONPATH=phase-loop-runtime/src python3 phase-loop-runtime/scripts/check_model_id_sources.py`; falsified by `PRESIDENT_LADDER` differing from `("sol", "fable", "grok", "gemini")`, a walk visiting rungs out of order, a rung resolving to a registry-superseded id, an unmarked id, or any other ACTIVE roadmap/contract/recipe text restating the order or naming a model id.
- [ ] EC-PRESROUTE-4 — proven by `grep -q 'EXPIRED by Consiliency/agent-harness#' plans/decision-interim-president-ratification-20260904.md` and `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_govlean_panel_policy.py -k "requires_president_false_refused"`; falsified by a `plan`/`production_code` landing carrying `requires_president=False` succeeding, or by the note lacking the EXPIRED row at merge.
- [ ] EC-PRESROUTE-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_president_wiring.py -k "ruling_record or findings_digest"`; falsified by a ruling with no stream record, a record whose findings digest differs from the findings the prompt carried, or a DEFERRED finding disappearing from the next round's ledger.
