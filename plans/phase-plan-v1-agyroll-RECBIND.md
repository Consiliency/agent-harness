---
phase_loop_plan_version: 1
phase: RECBIND
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 474825aa044e1d9f2d6989c37b08c226755fc6cea31f18c44e1609833fa42993
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_record_v2.py tests/test_agy_route_conformance.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py tests/test_outside_agent_release_surface.py tests/test_seat_reference_inventory.py && python scripts/verify_qualified_agy_image.py --contract"]
---

# RECBIND: Record binding and catalog decoupling

## Context

This is the first phase of AGYROLL. Its frozen input is
`plans/artifacts/agyroll-v1-contract.md`, with the sha256 pinned in the roadmap's External
Inputs. RECBIND implements:
- §2.1: `seat_qci()` and the semantic validator guard;
- §3.1: catalog v3 as package data;
- §3.2: record v2;
- §3.3: `--contract` on every PR, and `--release`;
- §3.4: the strict conformance suite;
- §3.5: record-commit migration.

The artifact is read-only during execution. A needed change goes back through an artifact
repin.

**Today's coupling** (main at this revision; the catalog is agy 1.5.3 from
agent-harness#1923):
- `gemini_heartbeat.QUALIFIED_IMAGES` is a literal in a route-core file.
- `scripts/verify_qualified_agy_image.py` parses that literal (`image_constants`), reads
  `plans/evidence/qualified-provider-images.json` (`catalog_route`), and compares each
  record's `source_sha256` against the tree. `--route-core` checks the three route-core files
  on every route PR (agent-harness#1029). `--source-only` checks all 288 sources at release
  (agent-harness#1032).
- `qualified-agy-image.yml` runs only on path-filtered PRs.
- `agy_watch.edit_constants` regex-edits the literal; `summarize` writes v1 records;
  `route_core_digest` labels PRs.
- `tests/data/seat_launch_references.json` inventories `edit_constants` and
  `route_core_digest`.
- `tests/test_agy_self_qualification.py::_watch_repo` *skips* when the old catalog file is
  missing.

**Gates.**
- EXT-0730 is met: agent-harness#1923 merged on 2026-11-08.
- **R1 must be recorded on agent-harness#1008 before execution.** If R1 keeps the pins, this
  plan is void: route a roadmap amendment (AGYROLL §6.4).

**Invariants.**
- `seat_qci()` equals `agy_profile_digest()` at `agy_validator_v1`, so no store key, no
  TEAMHOST §5 key and no host entry changes.
- The release fast path admits offline by digest.
- Everything is fail-closed.

## Interface Freeze Gates

- [ ] IF-0-RECBIND-1 — AGYROLL §2.1 and §3.1–§3.5, as frozen. They are published day-1 from the artifact:
  - `QUALIFICATION_VALIDATOR` and `seat_qci()` in `agy_qualification`;
  - `load_catalog(path=None) -> dict[str, str]` in `gemini_heartbeat`, which fills `QUALIFIED_IMAGES`;
  - `data/agy_catalog.json`, schema `qualified_agy_catalog.v3`, with the `published_at`, `pinned` and `capture_surface_sha256` fields;
  - record v2;
  - verifier flags `--contract`, `--release --conformance-report <junit.xml>` and `--upstream-only`.
- [ ] IF-0-RECBIND-2 — The strict conformance suite (AGYROLL §3.4):
  - entry point: `tests/test_agy_route_conformance.py`;
  - `CONFORMANCE_OBLIGATIONS`, six ids: three operations and three mutants;
  - `AGY_CONFORMANCE_STRICT=1`, under which a missing bwrap or userns fails rather than skips;
  - release CI runs `pytest tests/test_agy_route_conformance.py --junitxml=conformance.xml`, and `--release` consumes the report.

## Lane Index & Dependencies

SL-1 — Runtime QCI, validator guard and package-data catalog
  Depends on: (none)
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-2 — Record v2, verifier, converter, watch writers and workflows
  Depends on: SL-1, SL-3
  Blocks: SL-4
  Parallel-safe: yes

SL-3 — Strict hermetic route conformance suite
  Depends on: (none)
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-4 — Documentation & spec reconciliation
  Depends on: SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

| Lane | Size | Estimate |
|---|---|---|
| SL-1 | M | about 350 lines, including the semantic guard corpus |
| SL-2 | L | about 800 lines: verifier, converter and stop task, watch writers, two workflows, six test files and the inventory |
| SL-3 | L | about 550 lines, plus the stand-in, the mutants and strict mode |
| SL-4 | S | docs only |

## Lanes

### SL-1 — Runtime QCI, validator guard and package-data catalog
- **Scope**: Load the release member set from package data, and add `seat_qci()` together with the semantic validator guard, without changing any key value.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/tests/test_agy_qci.py`, `phase-loop-runtime/tests/test_agy_catalog_data.py`, `phase-loop-runtime/tests/fixtures/agy_validator_corpus/**`
- **Interfaces provided**: `load_catalog` (in `gemini_heartbeat`); `QUALIFIED_IMAGES`, a module-level `dict` that `monkeypatch.setitem` can still patch; `QUALIFICATION_VALIDATOR` and `seat_qci` (in `agy_qualification`).
- **Interfaces consumed**: (none)
- **Notes**:
  - **Loader.** It reads through `importlib.resources`. Validation is strict:
    - closed keys and hex64 digests;
    - unique images and versions;
    - `routes` == `{"linux-x64"}`;
    - `pinned` is a bool, and `capture_surface_sha256` is a hex64 or null.

    Any failure returns `{}`, never raises at import, and sets `CATALOG_STATUS`.
  - **Data file.** It is generated from the 1.5.3 literal, with `qci` = `seat_qci()` and with
    `asset_sha256` and `published_at` taken from the record and its release.
  - **Package data.** `pyproject.toml` adds `"data/agy_catalog.json"` to package-data.
  - **What stays.** `ROUTE_CORE`, `runtime_identity`, `PROFILE_ID` and
    `agy_profile_digest()` keep their values.
  - **Semantic guard (primary).**
    - The corpus under `tests/fixtures/agy_validator_corpus/` holds series directories. For
      each pass predicate there is one passing case and one failing case per way it can fail.
    - The guard pins `{QUALIFICATION_VALIDATOR: sha256(verdict vector)}`.
    - Mutants are monkeypatched into the transitive callees, including
      `panel_invoker.terminal_verdict` accepting a non-terminal stream. Each must change the
      vector, and the test asserts that the guard then fails without a literal bump.
  - **Supplement.** A source-hash table over the AST call-graph closure of `validate_records`,
    `validate_directory` and `_classify_failure` within `phase_loop_runtime`.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_agy_qci.py`, `tests/test_agy_catalog_data.py`, `tests/fixtures/agy_validator_corpus/**` | **Loader:** missing, malformed, extra-key, duplicate, wrong-route or empty files give `{}`, and `gh.admit` then has no release fast path. A data-file member is admitted `release_qualified` offline, with no store or network read. **QCI:** `seat_qci()` equals `agy_profile_digest()` at v1; a `__version__` or catalog edit leaves it unchanged; an `OPERATIONS_CONTRACT`, profile or validator-literal edit changes it. **Guard:** each mutant changes the verdict vector and fails the guard without a bump; the source-hash supplement covers the transitive closure. | `cd phase-loop-runtime && timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py` |
| SL-1.2 | impl | SL-1.1 | `gemini_heartbeat.py`, `agy_qualification.py`, `data/agy_catalog.json`, `pyproject.toml` | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | all SL-1 tests, plus the admission and inventory regressions | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py tests/test_seat_reference_inventory.py` |

### SL-2 — Record v2, verifier, converter, watch writers and workflows
- **Scope**: Bind records to `seat_qci()`. Retire `--route-core`, the full pin and the old catalog file. Run `--contract` on every PR, and gate a release on a strict conformance report plus `--release`.
- **Owned files**: `phase-loop-runtime/scripts/verify_qualified_agy_image.py`, `phase-loop-runtime/scripts/convert_agy_record_v2.py`, `phase-loop-runtime/scripts/agy_full_pin_scope.sh`, `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`, `plans/evidence/qualified-provider-images.json`, `plans/evidence/agy-*-linux-x64-qualification.json`, `.github/workflows/qualified-agy-image.yml`, `.github/workflows/publish-pypi.yml`, `phase-loop-runtime/tests/test_agy_record_v2.py`, `phase-loop-runtime/tests/test_qualified_agy_image_set.py`, `phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py`, `phase-loop-runtime/tests/test_agy_upstream_advisory.py`, `phase-loop-runtime/tests/test_outside_agent_release_surface.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: the verifier modes `--contract`, `--release --conformance-report` and `--upstream-only`; the record v2 writer `agy_watch.summarize`; `agy_watch.edit_catalog`, which replaces `edit_constants` and edits only the data file; the watch label `agy-qci:<seat_qci>`, which replaces the label from `route_core_digest`.
- **Interfaces consumed**: `seat_qci`, `load_catalog` (SL-1); `CONFORMANCE_OBLIGATIONS` (SL-3)
- **Notes**:
  - **Stop task (SL-2.0), first.** For each member, find the record commit (AGYROLL §3.5),
    then require `seat_qci` and the validator closure to be equal at that commit and at head.
    If no record commit exists, or either value differs, stop and report. That member needs
    one owner-approved live requalification, plus an amendment.
  - **Verifier.**
    - It parses the catalog strictly and fails on a malformed or empty one.
    - `--contract` runs on **every** PR and push. The workflow's path filters are removed,
      because the QCI reads `panel_invoker.py`.
    - `--release` requires a JUnit report whose obligation ids match
      `CONFORMANCE_OBLIGATIONS` exactly: each one passed, once, with zero skipped, xfailed or
      errored cases.
    - `--route-core` and `--source-only` are deleted.
  - **`publish-pypi.yml`.** Before the build, with `AGY_CONFORMANCE_STRICT=1`, run the suite
    with `--junitxml`, then `--release --conformance-report`. `--source-only` is gone.
  - **Watch tests.**
    - `_watch_repo` reads `data/agy_catalog.json`, and fails, rather than skips, in a repo
      checkout where the catalog is missing. The sdist-layout skip stays.
    - The inventory entries for `edit_constants` and `route_core_digest` become `edit_catalog`
      and the QCI label.
  - **Membership test.** `test_qualified_agy_image_set.py` stops pinning a version. It asserts
    that the runtime set equals the data file and the records, so an automated member PR does
    not need to edit a test.
  - **Deletions.** See Execution Notes.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.0 | verify | — | `scripts/convert_agy_record_v2.py`, `plans/evidence/agy-*-linux-x64-qualification.json` | Stop task: the record commit exists, and its QCI and validator closure equal head's. Otherwise stop and report. | `cd phase-loop-runtime && timeout 600 python3 scripts/convert_agy_record_v2.py --check` |
| SL-2.1 | test | SL-2.0 | the six SL-2 test files and the inventory | **Contract mode:** v2 closed; `--contract` passes non-QCI drift and fails QCI drift naming the member; a member with no record fails; an unlisted record is ignored; an empty or malformed catalog fails the verifier. **Release mode:** `--release` fails with no report, with a report that has a skipped, xfailed, missing or duplicated obligation, or with an asset mismatch. **Converter:** refuses a record with no record commit, and refuses on a QCI or closure mismatch. **Workflows:** `qualified-agy-image.yml` has no path filter and runs `--contract`; `publish-pypi.yml` runs strict conformance, then `--release`, and never `--source-only` or `--route-core`. **Watch:** `edit_catalog` touches only the data file; `_watch_repo` does not skip in a repo checkout; the inventory is exact. | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_record_v2.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_outside_agent_release_surface.py tests/test_agy_self_qualification.py tests/test_seat_reference_inventory.py` |
| SL-2.2 | impl | SL-2.1 | converter, verifier, `agy_watch.py`, evidence, workflows, inventory, deletions | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests, plus the verifier on the real evidence | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_record_v2.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_outside_agent_release_surface.py tests/test_agy_self_qualification.py tests/test_seat_reference_inventory.py && python scripts/verify_qualified_agy_image.py --contract` |

### SL-3 — Strict hermetic route conformance suite
- **Scope**: Prove in CI, without a provider, that the production qualification driver meets every pass predicate. This is the harness-side guarantee the full pin stood in for, and in strict mode it cannot pass by skipping.
- **Owned files**: `phase-loop-runtime/tests/test_agy_route_conformance.py`, `phase-loop-runtime/tests/fixtures/agy_conformance/**`
- **Interfaces provided**: `CONFORMANCE_OBLIGATIONS`, `IF-0-RECBIND-2`
- **Interfaces consumed**: `qualify_image` (pre-existing), `run_operation` (pre-existing) and the validator path, all read-only
- **Notes**:
  - **Stand-in.** A scripted stand-in under `tests/fixtures/agy_conformance/` speaks the
    stream-json surface implied by the redacted `records[]` shape. It uses no raw receipt.
  - **Operations.** `completion`, `cancel` and `owner-loss` run through `qualify_image` with
    the candidate admission, under the real profile and seal checks.
  - **Mutants.** Three mutants, each of which must fail its operation:
    - no terminal event;
    - an ignored cancel;
    - an orphaned child.
  - **Strict mode.** With `AGY_CONFORMANCE_STRICT=1`, a missing bwrap or userns is
    `pytest.fail`, and every obligation is a parametrized case whose id is in
    `CONFORMANCE_OBLIGATIONS`.
  - **Hard stop.** If the driver cannot run hermetically, stop and report an amendment
    (Assumption 3). Never mock the driver.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `tests/test_agy_route_conformance.py`, `tests/fixtures/agy_conformance/**` | Three operations pass with the conforming stand-in. Each mutant fails its operation. Strict mode fails on missing bwrap or userns. The obligation ids equal `CONFORMANCE_OBLIGATIONS`. | `cd phase-loop-runtime && AGY_CONFORMANCE_STRICT=1 timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_route_conformance.py` |
| SL-3.2 | impl | SL-3.1 | stand-in, mutants, strict-mode hook | — | — |
| SL-3.3 | verify | SL-3.2 | SL-3 owned files | all SL-3 tests | `cd phase-loop-runtime && AGY_CONFORMANCE_STRICT=1 timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_route_conformance.py --junitxml=/tmp/conformance.xml` |

### SL-4 — Documentation & spec reconciliation (SL-docs)

- **Scope**: Refresh the docs catalog, update the docs this phase invalidated, and append amendments.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `specs/phase-plans-agyroll-v1.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal)
- **Depends on**: SL-1, SL-2, SL-3

**Tasks**:

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-4.1 | docs | — | `.claude/docs-catalog.json` | Rescan with the scaffold helper when present; otherwise record "manual catalog audit". |
| SL-4.2 | docs | SL-4.1 | per catalog | **CONTRACTS** "qualified images": package data, record v2 and the strict release gate. **Release handoff:** drop "live requalification of every listed member". **Capabilities card:** the gate wording. **agy-upstream-watch:** `edit_catalog` and the QCI label. **CHANGELOG:** add an entry. |
| SL-4.3 | docs | SL-4.2 | `specs/phase-plans-agyroll-v1.md` | Append `### Post-execution amendments` if a freeze proved wrong. |
| SL-4.4 | verify | SL-4.3 | — | No doc linter is configured. Re-run `python -m phase_loop_runtime.roadmap_lint specs/phase-plans-agyroll-v1.md`. |

## Execution Notes

- **Single-writer files**:
  - SL-1: `gemini_heartbeat.py`, `agy_qualification.py`, `pyproject.toml`.
  - SL-2: both workflows, `agy_watch.py`, `tests/test_agy_self_qualification.py` (the watch section is the only change; SL-1 only runs this file) and `tests/data/seat_launch_references.json`.
  - Later phases: PROVFWD takes `agy_watch.py` and the verifier's `--upstream-only` fetch; REQUAL takes `agy_qualification.py`; ROLLJOB takes the verifier and `agy_watch.py` after PROVFWD.
- **Known destructive changes**:
  - `phase-loop-runtime/scripts/agy_full_pin_scope.sh` and `plans/evidence/qualified-provider-images.json` are deleted.
  - `source_sha256` is removed from member records.
  - The `--route-core` and `--source-only` paths are removed from `verify_qualified_agy_image.py`.
  - The `paths:` filters are removed from `qualified-agy-image.yml`.
- **Expected add/add conflicts**: none. Only the `plans/manifest.json` tail conflicts with agent-harness#1925 and agent-harness#1926; rebase and re-append.
- **No release dispatch.** This phase dispatches no release. The first cut that uses `--release` is EC-ACTIVATE-3.
- **Lockfile.** `uv.lock` is expected to stay unchanged. It is owned so that a resolver rewrite cannot leave an unowned dirty path.
- **Merge order.** SL-1 and SL-3 run in parallel, then SL-2 (SL-2.0 first), then SL-4.
- **Shared host.** Run only targeted pytest, serially, under `timeout`. Strict conformance and `--release` gate in CI. No live run and no `ai` access.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- SL-1: effort=high, reason=semantic validator guard must cover transitive predicates
- SL-2: effort=high, reason=release gate and evidence migration are security-relevant
- SL-3: effort=high, reason=hermetic driver harness under bwrap in strict mode
- SL-4: effort=low, reason=docs sweep only

## Acceptance Criteria

- [ ] EC-RECBIND-1 — Proven by `tests/test_agy_catalog_data.py` and `tests/test_agy_record_v2.py`. Falsified by a malformed `data/agy_catalog.json` admitting any image through `gemini_heartbeat.admit`, or by an empty catalog passing `--contract`.
- [ ] EC-RECBIND-2 — Proven by `tests/test_agy_qci.py`. Falsified by a verdict-changing validator mutant (including a `panel_invoker.terminal_verdict` mutant) passing the guard without a `QUALIFICATION_VALIDATOR` bump, or by a `__version__` bump or a catalog edit changing `seat_qci()`.
- [ ] EC-RECBIND-3 — Proven by `tests/test_agy_record_v2.py`, `tests/test_verify_qualified_agy_route_core.py` and `python scripts/verify_qualified_agy_image.py --contract`. Falsified by a record whose `qci` differs from the tree's passing `--contract`, or by a PR outside the old path filter not running `--contract`.
- [ ] EC-RECBIND-4 — Proven by `AGY_CONFORMANCE_STRICT=1 pytest tests/test_agy_route_conformance.py`. Falsified by any predicate mutant passing its operation through the production `qualify_image`.
- [ ] EC-RECBIND-5 — Proven by `tests/test_verify_qualified_agy_route_core.py` (workflow wiring) and `tests/test_agy_record_v2.py` (non-QCI drift passes, QCI drift fails). Falsified by a skipped conformance run passing `--release`, by a report with a skipped, xfailed or missing obligation passing, by `publish-pypi.yml` still invoking `--source-only`, or by an `OPERATIONS_CONTRACT` edit passing `--release`.
- [ ] EC-RECBIND-6 — Proven by `tests/test_agy_record_v2.py` and `scripts/convert_agy_record_v2.py --check`. Falsified by the converter accepting a record with no record commit, or one whose record-commit QCI or validator closure differs from head's.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_record_v2.py \
  tests/test_agy_route_conformance.py tests/test_qualified_agy_image_set.py \
  tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py \
  tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py \
  tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py \
  tests/test_outside_agent_release_surface.py tests/test_seat_reference_inventory.py
python scripts/verify_qualified_agy_image.py --contract
# CI / Gate A only: AGY_CONFORMANCE_STRICT=1 conformance with --junitxml, then --release --conformance-report
```

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/agy-*-linux-x64-qualification.json`
- redaction posture: `metadata_only`
- downstream handling: none
