---
phase_loop_plan_version: 1
phase: VISART
roadmap: specs/phase-plans-browser-v1.md
roadmap_sha256: 54aab672a3ff1f3ba5b5b4751ae912f91ae66d693e623bcfaff9b6d2192444a1
automation:
  suite_command: ["timeout", "900", "env", "PYTEST_ADDOPTS=", "python3", "-m", "pytest", "-p", "no:cacheprovider", "-q", "phase-loop-runtime/tests/test_browser_observation_contract.py", "phase-loop-runtime/tests/test_seat_visual_staging.py", "phase-loop-runtime/tests/test_seat_jail_visual_projection.py", "phase-loop-runtime/tests/test_board_visual_delivery.py", "phase-loop-runtime/tests/test_cli_observation.py", "phase-loop-runtime/tests/test_execute_skill_visual_capture.py", "phase-loop-runtime/tests/test_seat_jail.py", "phase-loop-runtime/tests/test_seat_reference_inventory.py", "phase-loop-runtime/tests/test_skills_bundle_drift.py", "phase-loop-runtime/tests/test_launchspec_golden.py"]
---

# VISART: Observation artifacts and seat staging

## Context

Roadmap phase VISART (`specs/phase-plans-browser-v1.md`). The goals are EC-VISART-1 to
EC-VISART-6, and every rule a lane implements is in the frozen contract
`plans/artifacts/browser-v1-contract.md` (§1–§7) and the schema
`plans/artifacts/browser-v1-observation.schema.json`, both pinned in the roadmap's External
Inputs. This plan does not restate them. No browser runs anywhere in this phase.

What exists today, and what each lane builds on:

- **Executor evidence.** Closeouts carry `visual_evidence_path`, which
  `models.resolve_visual_evidence_artifact` already checks for containment, regular file
  and image magic number. `visual_avatar_evidence_validator` feeds a warn-by-default gate.
  The capture guidance lives in `skills-src/codex/codex-execute-phase/SKILL.md` (the
  `visual_evidence_path` paragraph) and in the "Browser verification" section of
  `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`. Neither names
  T3 preview.
- **Seat views.** The jail (`seat_jail.build_seat_jail`, `_owner_argv`) binds the bundle
  and instructions as sealed memfds at `/seat/review`. `jail_profile_digest(leg)` covers
  the exact owner argv, and `actual_profile_digest` already strips the separately checked
  dependency-projection block before comparison. That block is the precedent for contract
  §4.3. The sandbox-profile route builds its view in `panel_invoker._seat_filesystem_view`
  from `SeatProfile.readonly_paths`. Brokered parent seats read the staged review directory.
  Native fill writes `native-fill/<request_id>/` from `cli._advisor_board_command`.
- **Board output.** `cli._advisor_board_command` builds the `--json` payload, including
  `legs`, and the text summary. The contract's `visual_evidence` block goes there.
- **Package data.** `schemas/*.json` already ships as package data, so the schema copy
  needs no `pyproject.toml` change. `jsonschema` is already a runtime dependency.

In-flight work on the same files: agent-harness#1916 (SEATS CODEX) edits `panel_invoker.py`,
`seat_jail.py`, `seat_profiles.py` and `sandbox_egress.py`. The roadmap's EXT-SEATSCODEX
gate holds SL-1 and SL-2 until it merges or closes. SL-0 and SL-3 may start now.

## Interface Freeze Gates

- [ ] IF-0-VISART-1 — `phase_loop_runtime.browser_observation` exports `SCHEMA_ID = "browser_observation.v1"`, `REFUSAL_CODES` (the eight `observation_*` codes of contract §7, a frozen tuple), `ObservationRefused(code, detail)`, frozen dataclasses `ObservationFile(path, sha256, bytes, media_type)` and `ObservationRecord(root, manifest, manifest_sha256, files)`, `load_observation(path) -> ObservationRecord` (raises on the first defect), `validate_observation(path) -> tuple[Finding, ...]` (every defect, each `Finding(code, path, detail)`), `render_index_html(manifest) -> bytes`, and `import_visual_evidence(images, *, out_dir, repo_root, tool, profile=None, url=None, viewport=None, color_scheme=None, source_commit=None, host=None, now=None) -> ObservationRecord`. The package schema `schemas/browser_observation.v1.schema.json` is byte-identical to the pinned artifact. Contract §2, §3, §7.
- [ ] IF-0-VISART-2 — `phase_loop_runtime.seat_visual_staging` exports frozen dataclasses `StagedVisual(logical_path, sha256, bytes, media_type)` and `VisualStage(root, observations, entries, stage_sha256)`, `stage_observations(records, review_dir) -> VisualStage | None` (None for no records; copies to `<review_dir>/visual/`), `revalidate_stage(stage) -> None` (raises `seat_visual_stage_changed`), and `bundle_appendix(stage, records) -> str` (contract §4.4, deterministic). `seat_jail` exports `VisualProjection` and `visual_projection(stage) -> VisualProjection` (sealed memfds plus the contiguous mount block), `build_seat_jail(..., visual: VisualProjection | None = None)`, and `actual_profile_digest` verifying then stripping that block. `seat_jail.NOTICES` gains `seat_visual_stage_changed`. Contract §4.
- [ ] IF-0-VISART-3 — CLI `phase-loop observation validate <dir> [--json]` and `phase-loop observation import …` with the contract §5 arguments and exit codes; `phase-loop advisor-board … --observation <dir>` (repeatable, at most 4, validated before composition). The board's `--json` payload gains top-level `visual_evidence` and per-leg `visual_delivered`; the text summary prints the same paths. Contract §5.

## Lane Index & Dependencies

SL-0 — Observation contract (preamble)
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-4
  Parallel-safe: no

SL-1 — Visual staging and jail projection
  Depends on: SL-0
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-2 — Board delivery, CLI and result block
  Depends on: SL-0, SL-1
  Blocks: SL-4
  Parallel-safe: no

SL-3 — Executor capture guidance and skill regeneration
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Documentation, inventory and spec reconciliation (SL-docs)
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Observation contract (preamble)

- **Scope**: Implement the `browser_observation.v1` loader, validator, writer, importer and deterministic `index.html` renderer, and ship the schema copy.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/browser_observation.v1.schema.json`, `phase-loop-runtime/tests/test_browser_observation_contract.py`, `phase-loop-runtime/tests/fixtures/browser-observation/**`
- **Interfaces provided**: IF-0-VISART-1
- **Interfaces consumed**: `models.resolve_visual_evidence_artifact` (pre-existing); the pinned schema and contract §2, §3, §7
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/test_browser_observation_contract.py`, `phase-loop-runtime/tests/fixtures/browser-observation/**` | Schema byte identity (sha256 `c5508465b49b87de775eda3e711ee5ef4727c6d5965ae4256a456575f2995080`); one valid executor and one valid broker fixture; one negative fixture per §7 `observation_*` code, each built by mutating a valid fixture through `load_observation` (symlink, hard link, `../` path, extra file, wrong magic, digest and size drift, each cap, `t3_preview` without `incognito`, `file:` and userinfo URLs, edited `index.html`); `index.html` determinism and its §3 forbidden-element scan; `import_visual_evidence` from images under a temp repo root | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_browser_observation_contract.py` |
| SL-0.2 | impl | SL-0.1 | `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/browser_observation.v1.schema.json` | — | — |
| SL-0.3 | verify | SL-0.2 | `phase-loop-runtime/src/phase_loop_runtime/browser_observation.py` | all SL-0 tests | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_browser_observation_contract.py` |

Files are opened with `O_NOFOLLOW` relative to a directory descriptor, and the manifest is
read once. The module imports nothing from `panel_invoker`, `seat_jail` or `cli`.

### SL-1 — Visual staging and jail projection

- **Scope**: Stage validated observations into the review directory, render the bundle appendix, and deliver the stage to jailed seats through a digest-neutral sealed-memfd projection.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/seat_visual_staging.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py`, `phase-loop-runtime/tests/test_seat_visual_staging.py`, `phase-loop-runtime/tests/test_seat_jail_visual_projection.py`, `phase-loop-runtime/tests/test_seat_jail.py`
- **Interfaces provided**: IF-0-VISART-2
- **Interfaces consumed**: IF-0-VISART-1 (`ObservationRecord`, `load_observation`, `ObservationRefused`); `seat_jail.jail_profile_digest`, `actual_profile_digest`, `_without_contiguous`, `_dependency_mount_destinations`, `_JAIL_PROTECTED_DESTINATIONS` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `phase-loop-runtime/tests/test_seat_visual_staging.py`, `phase-loop-runtime/tests/test_seat_jail_visual_projection.py` | Stage is a copy and its digest matches §4.1; a byte change after staging raises `seat_visual_stage_changed`; appendix is byte-stable and under 16 KiB; `jail_profile_digest(leg)` equals its pre-change value for every leg in `seat_profiles`; `actual_profile_digest` with and without a projection are equal; projection refuses a destination outside `/seat/review/visual/`, a path outside the §2 patterns, an unsealed or resized memfd, a byte mismatch, an over-cap stage and a foreign flag inside the block | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_visual_staging.py phase-loop-runtime/tests/test_seat_jail_visual_projection.py` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/seat_visual_staging.py`, `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py` | — | — |
| SL-1.3 | verify | SL-1.2 | `phase-loop-runtime/src/phase_loop_runtime/seat_jail.py` | SL-1 tests plus existing jail tests | `timeout 600 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_visual_staging.py phase-loop-runtime/tests/test_seat_jail_visual_projection.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_jail_qualification_entry.py` |

The digest test records each leg's `jail_profile_digest` from the base tree as a fixture
before SL-1.2 and asserts equality after. If equality cannot hold, the lane stops and
reports a roadmap amendment (Assumption 1); it never updates the fixture. New file-read
references go to SL-4 for the launch-reference inventory.

### SL-2 — Board delivery, CLI and result block

- **Scope**: Accept `--observation`, stage before composition, deliver per route, state each route's review-input root in its instructions, and emit the `visual_evidence` block and `observation` subcommands.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_board_visual_delivery.py`, `phase-loop-runtime/tests/test_cli_observation.py`, `phase-loop-runtime/tests/test_panel_invoker.py`
- **Interfaces provided**: IF-0-VISART-3
- **Interfaces consumed**: IF-0-VISART-1 (`load_observation`, `validate_observation`, `import_visual_evidence`, `REFUSAL_CODES`); IF-0-VISART-2 (`stage_observations`, `revalidate_stage`, `bundle_appendix`, `visual_projection`, `build_seat_jail(visual=…)`); `SeatProfile.readonly_paths`, `_seat_filesystem_view`, `invoke_board` (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `phase-loop-runtime/tests/test_board_visual_delivery.py`, `phase-loop-runtime/tests/test_cli_observation.py` | Each §4.2 route, entered through `invoke_board` with a fake provider, sees the stage read-only at its root's `visual/` (jail: the owner argv's projection block; sandbox: a read-only bind; parent: the staged directory; native fill: copy beside `artifact.md` with `request.json` bytes unchanged) or records `visual_delivered: false` (remote); bundle ends with the appendix; an invalid `--observation` exits 2 with zero seat launches; a fifth observation exits 2; `observation validate|import` exit codes and JSON; `visual_evidence` block fields; no seat egress allowlist digest changes | `timeout 600 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_board_visual_delivery.py phase-loop-runtime/tests/test_cli_observation.py` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py` | — | — |
| SL-2.3 | verify | SL-2.2 | `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py` | SL-2 tests plus board regressions | `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_board_visual_delivery.py phase-loop-runtime/tests/test_cli_observation.py phase-loop-runtime/tests/test_broker_staged_tree_delivery.py phase-loop-runtime/tests/test_review_stage_binding.py phase-loop-runtime/tests/test_sandbox_egress.py` |

Observation validation runs before composition, so a refusal spends no seat. The stage is
revalidated immediately before each launch. The appendix is appended to the staged bundle
before the bundle digest is taken, so every seat reviews the same bytes.

### SL-3 — Executor capture guidance and skill regeneration

- **Scope**: Name T3 preview on the `incognito` profile as a capture source and direct observation import and the board flag in the execute skills, then regenerate the bundles and goldens.
- **Owned files**: `skills-src/codex/codex-execute-phase/SKILL.md`, `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`, `phase-loop-skills/execute-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-phase/**`, `phase-loop-runtime/tests/data/launchspec_golden/**`, `phase-loop-runtime/tests/test_execute_skill_visual_capture.py`
- **Interfaces provided**: (none)
- **Interfaces consumed**: contract §5 and §6 text (pre-existing)
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/test_execute_skill_visual_capture.py` | Each execute-skill source and its generated bundle copy names the three capture sources, `profileId: "incognito"`, `phase-loop observation import` and `--observation`, and never presents T3's default or a named profile as acceptable; paired with the drift and golden tests | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_execute_skill_visual_capture.py` |
| SL-3.2 | impl | SL-3.1 | `skills-src/codex/codex-execute-phase/SKILL.md`, `skills-src/claude/claude-execute-phase/references/merge-and-verify.md`, `phase-loop-skills/execute-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-phase/**`, `phase-loop-runtime/tests/data/launchspec_golden/**` | — | — |
| SL-3.3 | verify | SL-3.2 | generated outputs | SL-3 test plus drift and golden | `timeout 600 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_execute_skill_visual_capture.py phase-loop-runtime/tests/test_skills_bundle_drift.py phase-loop-runtime/tests/test_launchspec_golden.py` |

SL-3.2 edits only the two sources, then runs `python phase-loop-runtime/scripts/regenerate_skills_bundle.py`
and `python phase-loop-runtime/scripts/sync_skills_bundle.py`. Generated files are never
hand-edited. The guidance never tells an executor to open a browser for a seat.

### SL-4 — Documentation, inventory and spec reconciliation (SL-docs)

- **Scope**: Single writer of shared docs and the launch-reference inventory; records the phase evidence.
- **Owned files**: `docs/browser-observation.md`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `.claude/docs-catalog.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `plans/evidence/browser/VISART.md`, `specs/phase-plans-browser-v1.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-VISART-1, IF-0-VISART-2, IF-0-VISART-3
- **Parallel-safe**: no (terminal)

It also takes the new launch references SL-1 and SL-2 report, and SL-3's regenerated text.

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-docs.1 | docs | — | `.claude/docs-catalog.json` | Rescan with `python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if the helper is absent, record "manual catalog audit". |
| SL-docs.2 | docs | SL-docs.1 | `docs/browser-observation.md`, `CONTRACTS.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.doc-decisions.json`, `phase-loop-runtime/tests/data/seat_launch_references.json` | New guide: the artifact, `observation import|validate`, `--observation`, viewing in T3 and desktop or mobile Chrome, OR-4's linked `ai` environment and copy fallback. CONTRACTS.md adds `/seat/review/visual` to the jail profile text and states it is outside the base digest. Card and `[Unreleased]` entry. Inventory rows for SL-1 and SL-2 references. |
| SL-docs.3 | docs | SL-docs.2 | `specs/phase-plans-browser-v1.md`, `plans/evidence/browser/VISART.md` | Metadata-only evidence: test receipts, the per-leg digest-equality result, the regenerated-bundle check. Append `### Post-execution amendments` to VISART only if a freeze proved wrong. |
| SL-docs.4 | verify | SL-docs.3 | — | `timeout 300 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q phase-loop-runtime/tests/test_seat_reference_inventory.py`, then `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-browser-v1.md`, then the hosted docs-freshness audit. |

## Execution Notes

- **EXT-SEATSCODEX.** SL-1 and SL-2 start only after agent-harness#1916 merges or closes.
  SL-0 and SL-3 start now.
- **Single-writer files**: `seat_jail.py` (SL-1); `panel_invoker.py` and `cli.py` (SL-2);
  `seat_launch_references.json` (SL-4). VISBROKER and VISHARDEN edit `panel_invoker.py`
  later, and AGYROLL REQUAL and EXECADMIT (agent-harness#1927) also edit it; serialize by
  landing order. No VISART lane edits `seat_profiles.py`, `sandbox_egress.py`,
  `seat_egress_proxy.py` or an `agy_qualification.ROUTE_CORE` file.
- **No release.** This phase dispatches no release, tag or external workflow, so it has no
  post-dispatch evidence reducer.
- **Companion tests**: SL-1 owns `test_seat_jail.py` and SL-2 owns `test_panel_invoker.py`
  only so a needed regression edit is owned; neither is expected to change.
- **Known destructive changes**: none — every lane is purely additive.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none; callers import `phase_loop_runtime.browser_observation` directly.
- **Generated files**: SL-3 alone writes `phase-loop-skills/**`, `skills_bundle/**` and the
  launch-spec golden, through the two regeneration scripts.
- **Shared-host limits**: every command here is targeted, serial (no `-n`, so it runs with or without pytest-xdist) and under `timeout`. No
  test starts a browser, a seat provider or a network listener. Full suites run on hosted
  CI and Gate A.
- **Worktree naming**: claude-execute-phase allocates unique worktree names via `scripts/allocate_worktree_name.sh`. Plan doc does not need to spell out lane worktree paths.
- **Stale-base guidance**: Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- execute: effort=medium, reason=bounded contract work with frozen inputs
- SL-1: effort=high, reason=jail argv and digest stripping are security sensitive
- SL-2: effort=high, reason=delivery spans five launch paths in panel_invoker
- SL-3: effort=low, reason=skill text plus scripted regeneration
- SL-4: effort=low, reason=documentation reducer

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/browser-observation.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/browser/VISART.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Acceptance Criteria

- [ ] EC-VISART-1 — proven by `V0` (`test_browser_observation_contract.py`), falsified by any §7 negative fixture loading cleanly or by a valid fixture refused. Path-entered control: each fixture enters through `load_observation` on a real directory.
- [ ] EC-VISART-2 — proven by `V0` and `V2` (`test_cli_observation.py`), falsified by `observation import --tool t3_preview` without `--profile incognito` exiting 0, or by two imports of the same images yielding different `index.html` bytes. Path-entered control: images enter through the installed `phase-loop observation import` entry point and `resolve_visual_evidence_artifact`.
- [ ] EC-VISART-3 — proven by `V2` (`test_board_visual_delivery.py`), falsified by a local route whose seat view lacks `visual/`, by a writable visual path, or by an invalid observation reaching a seat launch. Path-entered control: observations enter through `phase-loop advisor-board --observation` and `invoke_board` with a fake provider.
- [ ] EC-VISART-4 — proven by `V1` (`test_seat_jail_visual_projection.py`, `test_seat_jail.py`) and `V2`, falsified by any leg's `jail_profile_digest` differing from the base fixture, by unequal `actual_profile_digest` with and without visuals, by a changed seat egress digest, or by an out-of-prefix destination, unsealed memfd or post-staging byte change launching. Path-entered control: the projection enters through `build_seat_jail(visual=…)`.
- [ ] EC-VISART-5 — proven by `V2` (`test_cli_observation.py`, `test_board_visual_delivery.py`), falsified by a `--json` payload missing any `visual_evidence` field from contract §5 or any leg missing `visual_delivered`, or by the remote route reporting `true`. Path-entered control: through `cli.main(["advisor-board", …])`.
- [ ] EC-VISART-6 — proven by `V3` (`test_execute_skill_visual_capture.py`, `test_skills_bundle_drift.py`, `test_launchspec_golden.py`), falsified by a generated bundle that differs from its regenerated source, or by guidance that accepts T3's default profile. Path-entered control: text enters through the two `skills-src` files and the regeneration scripts.

## Verification

`P` is `timeout 900 env PYTEST_ADDOPTS= python3 -m pytest -p no:cacheprovider -q`, with
file paths under `phase-loop-runtime/tests/`. On this plan-only checkout the new test files
are absent, so these are pending selectors, not receipts.

- `V0`: `P test_browser_observation_contract.py`
- `V1`: `P test_seat_visual_staging.py test_seat_jail_visual_projection.py test_seat_jail.py test_seat_jail_qualification_entry.py`
- `V2`: `P test_board_visual_delivery.py test_cli_observation.py test_broker_staged_tree_delivery.py test_review_stage_binding.py test_sandbox_egress.py`
- `V3`: `P test_execute_skill_visual_capture.py test_skills_bundle_drift.py test_launchspec_golden.py`
- `V4`: `P test_seat_reference_inventory.py`, then `timeout 120 phase-loop validate-roadmap --repo . --roadmap specs/phase-plans-browser-v1.md`
- Visual check (no browser in any sandbox): open one fixture observation's `index.html` in a desktop Chrome and a mobile-width Chrome viewport, and view one staged PNG inline in T3 by absolute path; record the result in `plans/evidence/browser/VISART.md`.
- Full suite: hosted CI and Gate A only.
