---
phase_loop_plan_version: 1
phase: RECBIND
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: b345e910cacb2c872a4aa0b5b77131d3baae432b4c56a5dfea7b43e174f80c33
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_record_v2.py tests/test_agy_route_conformance.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py tests/test_outside_agent_release_surface.py && python scripts/verify_qualified_agy_image.py --contract"]
---

# RECBIND: Record binding and catalog decoupling

## Context

This is the first phase of AGYROLL. The frozen input is
`plans/artifacts/agyroll-v1-contract.md` (sha256 pinned in the roadmap's External Inputs).
This phase implements §2.1 (`seat_qci()`), §3.1 (catalog v3 as package data), §3.2
(record v2), §3.3 (`--contract`/`--release`), §3.4 (conformance suite) and §3.5
(migration). The artifact is read-only during execution. A needed contract change goes
back through an artifact repin.

**Today's coupling** (read on main at planning time):

- `gemini_heartbeat.QUALIFIED_IMAGES` is a literal in a route-core file.
- `scripts/verify_qualified_agy_image.py` parses that literal with the AST
  (`image_constants`), reads `plans/evidence/qualified-provider-images.json`
  (`catalog_route`, schema v2), and compares each record's `source_sha256` against the
  checkout:
  - `--route-core` checks the three route-core files;
  - `--source-only` checks all ~285 sources.
- `publish-pypi.yml` runs `--source-only` before the build, which forces a hand live run
  at every release.
- `qualified-agy-image.yml` runs `--route-core`, plus `--source-only` whenever
  `scripts/agy_full_pin_scope.sh` says so.
- `agy_watch.edit_constants` regex-edits the literal plus the catalog; `summarize` writes
  v1 records with `source_sha256`; `route_core_digest` labels watch PRs.

The result: adding a member, or cutting a release, requalifies every member.

**Gates before work starts:**

- **EXT-0730.** agent-harness#1923 has merged or been abandoned. The converter runs on
  whatever members exist at that point.
- **R1.** The owner ruling is recorded on agent-harness#1008. If R1 keeps the full pin,
  this plan is void: route a roadmap amendment (AGYROLL §6.4 variant) and do not execute.

**Invariants:**

- `agy_profile_digest()` keeps its value, so host stores do not drop in this phase.
- The release fast path still admits offline by digest.
- Every refusal stays fail-closed.

## Interface Freeze Gates

- [ ] IF-0-RECBIND-1 — AGYROLL §2.1 and §3.1–§3.5, as frozen. This is published on day 1 from the artifact, so every lane starts against these names:
  - `agy_qualification.QUALIFICATION_VALIDATOR` and `agy_qualification.seat_qci()`;
  - `gemini_heartbeat.load_catalog(path=None) -> dict[str, str]`, which fills `QUALIFIED_IMAGES`;
  - `phase_loop_runtime/data/agy_catalog.json` (`qualified_agy_catalog.v3`);
  - record v2;
  - verifier flags `--contract`, `--release` and `--upstream-only`.
- [ ] IF-0-RECBIND-2 — The conformance entry point `tests/test_agy_route_conformance.py`, runnable as `pytest -q -n 0 tests/test_agy_route_conformance.py`. It needs bubblewrap and user namespaces, and skips (never passes) when the host lacks them. The `publish-pypi.yml` release step runs it on the release commit before `--release`.

## Lane Index & Dependencies

SL-1 — Runtime QCI and package-data catalog
  Depends on: (none)
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-2 — Record v2, verifier, converter, watch writers and workflows
  Depends on: SL-1, SL-3
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Hermetic route conformance suite
  Depends on: (none)
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-4 — Documentation & spec reconciliation
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

| Lane | Size | Estimate |
|---|---|---|
| SL-1 | M | ~250 changed lines including tests |
| SL-2 | L | ~700 lines: verifier rewrite, converter, watch writers, two workflows, four test files |
| SL-3 | L | ~500 lines plus a scripted stand-in fixture |
| SL-4 | S | docs only |

## Lanes

### SL-1 — Runtime QCI and package-data catalog
- **Scope**: Load the release member set from package data, and add `seat_qci()` without changing `agy_profile_digest()`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/tests/test_agy_qci.py`, `phase-loop-runtime/tests/test_agy_catalog_data.py`
- **Interfaces provided**: `load_catalog` (in `gemini_heartbeat`), `QUALIFIED_IMAGES` (a module-level `dict`, still `monkeypatch.setitem`-able), `QUALIFICATION_VALIDATOR` and `seat_qci` (in `agy_qualification`)
- **Interfaces consumed**: (none)
- **Notes**:
  - **Loader.** The loader uses `importlib.resources` and validates strictly (closed keys, hex64 digests, unique images and versions, `routes` == `{"linux-x64"}`). Any failure returns `{}`, never raises at import, and records `catalog_status` for the doctor.
  - **Data file.** `agy_catalog.json` is generated once from the literal at EXT-0730, with `qci` = `seat_qci()` and `asset_sha256` taken from each member's record.
  - **Package data.** `pyproject.toml` adds `"data/agy_catalog.json"` to package-data.
  - **What stays.** `ROUTE_CORE`, `runtime_identity` and `PROFILE_ID` keep their values.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_agy_qci.py`, `tests/test_agy_catalog_data.py` | Loader: missing, malformed, extra-key, duplicate and wrong-route files each give `{}`, and `gh.admit` then has no release fast path. A data-file member is admitted `release_qualified` offline, with no store or network read. `seat_qci()` does not change on a `__version__` or catalog edit, and changes on an `OPERATIONS_CONTRACT`, profile or `QUALIFICATION_VALIDATOR` edit. `agy_profile_digest()` equals the base tree's value, recorded in the test. Validator guard: a frozen `{validator literal: sha256 of the validator function sources}` table goes red when those sources change without a literal bump. | `cd phase-loop-runtime && timeout 600 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py` |
| SL-1.2 | impl | SL-1.1 | `gemini_heartbeat.py`, `agy_qualification.py`, `data/agy_catalog.json`, `pyproject.toml` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | all SL-1 tests plus the admission regressions | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py` |

### SL-2 — Record v2, verifier, converter, watch writers and workflows
- **Scope**: Bind records to `seat_qci()`, retire the source pins and the old catalog file, and rewire both workflows to `--contract`/`--release`.
- **Owned files**: `phase-loop-runtime/scripts/verify_qualified_agy_image.py`, `phase-loop-runtime/scripts/convert_agy_record_v2.py`, `phase-loop-runtime/scripts/agy_full_pin_scope.sh`, `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`, `plans/evidence/qualified-provider-images.json`, `plans/evidence/agy-*-linux-x64-qualification.json`, `.github/workflows/qualified-agy-image.yml`, `.github/workflows/publish-pypi.yml`, `phase-loop-runtime/tests/test_agy_record_v2.py`, `phase-loop-runtime/tests/test_qualified_agy_image_set.py`, `phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py`, `phase-loop-runtime/tests/test_agy_upstream_advisory.py`, `phase-loop-runtime/tests/test_outside_agent_release_surface.py`
- **Interfaces provided**: verifier modes `--contract`, `--release` and `--upstream-only`; the record v2 writer `agy_watch.summarize`; `agy_watch.edit_catalog`, which replaces `edit_constants` and edits only the data file; and the watch PR label `agy-qci:<seat_qci>`, which replaces the route-core digest label
- **Interfaces consumed**: `seat_qci`, `load_catalog` (SL-1); `IF-0-RECBIND-2` (SL-3)
- **Notes**:
  - **Order of work.** Run the converter first, on the pre-lane base. It requires that each v1 `source_sha256` equals that tree's sources, then writes v2 records with `qci` from head's `seat_qci()`.
  - **Record v2 tests** prove the conversion, and the R1 behaviour:
    - `agy_profile_digest()` and the validator sources are equal at base and head (EC-RECBIND-6);
    - a tree that drifts only outside the QCI passes `--contract` and `--release`;
    - editing `OPERATIONS_CONTRACT` or the validator literal fails both and prints `requalify: <member>`.
  - **Verifier cleanup.** `--route-core` and `--source-only` are deleted.
  - **Catalog-membership test.** `test_qualified_agy_image_set.py` stops pinning a version literal. It asserts that the runtime set equals the data file and the record set (EC-RECBIND-3), so an automated member PR does not need to edit a test.
  - **Deletions.** `agy_full_pin_scope.sh` and `plans/evidence/qualified-provider-images.json` are deleted; see Execution Notes.
  - **Workflows.**
    - `qualified-agy-image.yml`: path filters add `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json`; PRs and pushes run `--contract`; nightly keeps `--upstream-only`.
    - `publish-pypi.yml`: the release step runs the conformance suite and then `--release`, before the build.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_agy_record_v2.py`, `tests/test_qualified_agy_image_set.py`, `tests/test_verify_qualified_agy_route_core.py`, `tests/test_agy_upstream_advisory.py`, `tests/test_outside_agent_release_surface.py` | v2 schema closed; `--contract` passes non-QCI drift and fails QCI drift naming the member; a catalog entry without a record fails; an unlisted record is ignored; a wrong record `qci` fails; the converter refuses a v1 record whose pins differ from the base tree; base and head QCI are equal; `--release` fails on an asset digest mismatch; `publish-pypi.yml` runs conformance before `--release` and never `--source-only`; `qualified-agy-image.yml` runs `--contract` on every PR; `agy_watch.edit_catalog` changes only the data file and never `gemini_heartbeat.py` | `cd phase-loop-runtime && timeout 600 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_record_v2.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_outside_agent_release_surface.py` |
| SL-2.2 | impl | SL-2.1 | converter, verifier, `agy_watch.py`, evidence, workflows, deletions | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests, plus the verifier on the real evidence | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_record_v2.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_outside_agent_release_surface.py && python scripts/verify_qualified_agy_image.py --contract` |

### SL-3 — Hermetic route conformance suite
- **Scope**: Prove in CI, with no provider, that the production qualification driver still meets every pass predicate. This is the harness-side guarantee the full source pin stood in for.
- **Owned files**: `phase-loop-runtime/tests/test_agy_route_conformance.py`, `phase-loop-runtime/tests/fixtures/agy_conformance/**`
- **Interfaces provided**: `IF-0-RECBIND-2`
- **Interfaces consumed**: `qualify_image` (pre-existing), `run_operation` (pre-existing) and the validator path, all read-only
- **Notes**:
  - **The stand-in.** It is a scripted executable under `tests/fixtures/agy_conformance/`. It speaks the stream-json surface implied by the redacted record shape (`records[]` rows) and never uses a raw receipt.
  - **The run.** The suite runs `completion`, `cancel` and `owner-loss` through `qualify_image` with the candidate admission, under the real profile and seal checks.
  - **Mutants.** One mutant per predicate: no terminal event, a cancel that is ignored, and a child that survives owner loss. Each must make its operation fail with a `failed` classification.
  - **Hard stop.** If the driver cannot run hermetically under bwrap and user namespaces, stop and report a roadmap amendment (Assumption 3). Never mock the driver.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `tests/test_agy_route_conformance.py`, `tests/fixtures/agy_conformance/**` | three operations pass with the conforming stand-in; each mutant fails its operation; skips with a reason when the host lacks bwrap or userns | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_route_conformance.py` |
| SL-3.2 | impl | SL-3.1 | fixture stand-in and mutants | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 owned files | all SL-3 tests | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider tests/test_agy_route_conformance.py` |

### SL-4 — Documentation & spec reconciliation (SL-docs)

- **Scope**: Refresh the docs catalog, update the docs this phase invalidated, and append amendments.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `specs/phase-plans-agyroll-v1.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal)
- **Depends on**: SL-1, SL-2, SL-3

**Tasks**:

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-4.1 | docs | — | `.claude/docs-catalog.json` | Rescan with the scaffold helper when it is present; otherwise record "manual catalog audit". |
| SL-4.2 | docs | SL-4.1 | per catalog | CONTRACTS "qualified images": package data plus record v2. Release handoff: drop "live requalification of every listed member", and the cut runs conformance plus `--release`. agy-upstream-watch: `edit_catalog` and the QCI label. CHANGELOG entry. |
| SL-4.3 | docs | SL-4.2 | `specs/phase-plans-agyroll-v1.md` | Append `### Post-execution amendments` if a freeze proved wrong. |
| SL-4.4 | verify | SL-4.3 | — | No doc linter is configured. Re-run `phase-loop validate-roadmap specs/phase-plans-agyroll-v1.md`. |

## Execution Notes

- **Single-writer files**:
  - `gemini_heartbeat.py`, `agy_qualification.py` and `pyproject.toml`: SL-1.
  - Both workflows and `agy_watch.py`: SL-2.
  - In later phases, REQUAL takes `agy_qualification.py`, and ROLLJOB takes the verifier and `agy_watch.py`.
- **Known destructive changes**:
  - `phase-loop-runtime/scripts/agy_full_pin_scope.sh` is deleted.
  - `plans/evidence/qualified-provider-images.json` is deleted.
  - `source_sha256` is removed from member records.
  - The `--route-core`/`--source-only` code paths are removed from `verify_qualified_agy_image.py`.
- **Expected add/add conflicts**: none.
- **No release dispatch.** This phase changes the release gate but dispatches no release, so it needs no post-dispatch evidence reducer. The first release cut that uses `--release` is ACTIVATE's EC-ACTIVATE-3.
- **Lockfile.** `uv.lock` is expected to stay unchanged; SL-1 owns it only so that a resolver rewrite cannot leave an unowned dirty path.
- **Merge order.** SL-1 and SL-3 in parallel, then SL-2, then SL-docs (SL-4). SL-2's converter must run before SL-1's head changes anything the converter's base-equality check reads, so run it on SL-1's merge base and commit its output in SL-2.
- **Shared host.** Use targeted pytest only, with `-n 0`, under `timeout`. The conformance suite and `--release` gate run in CI. Nothing here needs a live run or access to `ai`.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- SL-1: effort=medium, reason=bounded loader and digest wrapper
- SL-2: effort=high, reason=release gate and evidence migration are security-relevant
- SL-3: effort=high, reason=hermetic driver harness under bwrap
- SL-4: effort=low, reason=docs sweep only

## Acceptance Criteria

- [ ] EC-RECBIND-1 — Proven by `tests/test_agy_catalog_data.py`. Falsified by a malformed `data/agy_catalog.json` admitting any image through the release fast path in `gemini_heartbeat.admit`.
- [ ] EC-RECBIND-2 — Proven by `tests/test_agy_qci.py`. Falsified by a validator-source edit without a `QUALIFICATION_VALIDATOR` bump passing, or by a `__version__` bump changing `seat_qci()`.
- [ ] EC-RECBIND-3 — Proven by `tests/test_agy_record_v2.py` and `python scripts/verify_qualified_agy_image.py --contract`. Falsified by a record whose `qci` differs from the tree's passing `--contract`.
- [ ] EC-RECBIND-4 — Proven by `tests/test_agy_route_conformance.py`. Falsified by any predicate mutant (no terminal event, an ignored cancel, an orphaned child) passing its operation through the production `qualify_image`.
- [ ] EC-RECBIND-5 — Proven by `tests/test_verify_qualified_agy_route_core.py` (workflow wiring) and `tests/test_agy_record_v2.py` (non-QCI drift passes `--release`). Falsified by `publish-pypi.yml` still invoking `--source-only`, or by an `OPERATIONS_CONTRACT` edit passing `--release`.
- [ ] EC-RECBIND-6 — Proven by `tests/test_agy_record_v2.py` (converter base equality and base/head QCI equality). Falsified by the converter accepting a v1 record whose `source_sha256` differs from its base tree.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider \
  tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_record_v2.py \
  tests/test_agy_route_conformance.py tests/test_qualified_agy_image_set.py \
  tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py \
  tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py \
  tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py \
  tests/test_outside_agent_release_surface.py
python scripts/verify_qualified_agy_image.py --contract
# CI / Gate A only: conformance suite then --release on the release commit
```

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`
- evidence paths: `plans/evidence/agy-*-linux-x64-qualification.json`
- redaction posture: `metadata_only`
- downstream handling: none
