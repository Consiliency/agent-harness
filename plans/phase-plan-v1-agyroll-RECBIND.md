---
phase_loop_plan_version: 1
phase: RECBIND
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 047c83b3a4bdcd82fd9a3c6e9263bbe78cc9b1821b1052584a6f25c86f277f15
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_record_v2.py tests/test_agy_route_conformance.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py tests/test_outside_agent_release_surface.py tests/test_seat_reference_inventory.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# RECBIND: Record binding and catalog decoupling

## Context

This is the first phase of AGYROLL. Its frozen input is
`plans/artifacts/agyroll-v1-contract.md`, with the sha256 pinned in the roadmap's External
Inputs. RECBIND implements:
- §2.1: `seat_qci()` and the semantic validator guard;
- §3.1: catalog v3 as package data;
- §3.2: record v2;
- §3.3: `--contract` on every PR, plus `--release`;
- §3.4: the strict conformance suite;
- §3.5: record-commit migration.

The artifact is read-only during execution. A needed change goes back through an artifact
repin.

**Today's coupling** (main at this revision; the catalog holds agy 1.5.3 from
agent-harness#1923):
- `gemini_heartbeat.QUALIFIED_IMAGES` is a literal in a route-core file.
- `scripts/verify_qualified_agy_image.py` parses that literal (`image_constants`) and reads
  `plans/evidence/qualified-provider-images.json`. It compares each record's `source_sha256`
  against the tree in two modes:
  - `--route-core`, on every route PR (agent-harness#1029);
  - `--source-only`, over all 288 sources at release (agent-harness#1032).
- `qualified-agy-image.yml` runs only on path-filtered PRs.
- `agy_watch.edit_constants` regex-edits the literal, `summarize` writes v1 records, and
  `route_core_digest` labels PRs.
- In `tests/test_agy_self_qualification.py`, the watch and verifier tests parse the literal
  and call `edit_constants`, and `_watch_repo` *skips* when the old catalog file is missing.
- `tests/data/seat_launch_references.json` is an exact inventory. It lists `edit_constants`
  and `route_core_digest`, and it would need a row for the new `load_catalog` `io.read_text`.

These couplings are why the runtime, record and verifier work forms **one sequential lane**
(SL-1). Splitting it would either leave a lane's verify step red, or give two lanes the same
owned file, which the lane-IR `overlapping_write_ownership` check refuses regardless of
dependencies.

**Gates.**
- **EXT-0730** is met: agent-harness#1923 merged on 2026-11-08.
- **R1** was approved by the owner on 2026-11-08 (recorded on agent-harness#1008). Its
  conditions are binding:
  - conformance cannot pass by skipping: SL-2's strict mode plus SL-1's `--release` report
    check;
  - the semantic validator guard covers transitive predicates (SL-1);
  - both removed gates, `--route-core` (agent-harness#1029) and the full pin
    (agent-harness#1032), are named and deleted (SL-1).

  A lane that cannot meet a condition stops and routes an amendment.

**Invariants.**
- `seat_qci()` equals `agy_profile_digest()` at `agy_validator_v1`. No store key, TEAMHOST
  §5 key or host entry changes.
- The release fast path still admits offline by digest.
- Everything fails closed.

## Interface Freeze Gates

- [ ] IF-0-RECBIND-1 — AGYROLL §2.1 and §3.1–§3.5, as frozen and published on day 1:
  - `QUALIFICATION_VALIDATOR` and `seat_qci()` in `agy_qualification`;
  - `load_catalog(path=None) -> dict[str, str]` in `gemini_heartbeat`, which fills `QUALIFIED_IMAGES`;
  - `data/agy_catalog.json`, schema `qualified_agy_catalog.v3`, with `published_at` and `pinned` (no capture-surface field, because R3 is approved);
  - record v2;
  - verifier flags `--contract`, `--release --conformance-report <junit.xml>` and `--upstream-only`;
  - `scripts/convert_agy_record_v2.py --check|--write`.
- [ ] IF-0-RECBIND-2 — The strict conformance suite (AGYROLL §3.4):
  - entry point `tests/test_agy_route_conformance.py`;
  - `CONFORMANCE_OBLIGATIONS`: six ids, three operations and three mutants;
  - `AGY_CONFORMANCE_STRICT=1`, under which a missing bwrap or user namespace is a failure, not a skip;
  - release CI writes the JUnit report under `$RUNNER_TEMP`, and `--release` consumes it.

## Lane Index & Dependencies

SL-1 — Catalog, QCI, guard, records, verifier, watch writers and workflows
  Depends on: SL-2
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Strict hermetic route conformance suite
  Depends on: (none)
  Blocks: SL-1, SL-3
  Parallel-safe: yes

SL-3 — Documentation & spec reconciliation
  Depends on: SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

| Lane | Size | Estimate |
|---|---|---|
| SL-1 | XL | about 1,150 lines, in three ordered test/impl pairs: converter check, runtime, then records/verifier/watch/workflows/inventory |
| SL-2 | L | about 550 lines, plus the stand-in, the mutants and strict mode |
| SL-3 | S | docs only |

SL-1 consumes SL-2's `CONFORMANCE_OBLIGATIONS`, so the order is SL-2, then SL-1, then SL-3.
SL-2 is the smaller lane and touches only tests and fixtures.

## Lanes

### SL-1 — Catalog, QCI, guard, records, verifier, watch writers and workflows
- **Scope**: Prove each record's provenance first. Then move the catalog to package data, add `seat_qci()` and the semantic guard, and bind records to the QCI. Retire `--route-core`, the full pin and the old catalog file. Run `--contract` on every PR, and gate releases on a strict conformance report plus `--release`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/gemini_heartbeat.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`, `phase-loop-runtime/src/phase_loop_runtime/data/agy_catalog.json`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/scripts/verify_qualified_agy_image.py`, `phase-loop-runtime/scripts/convert_agy_record_v2.py`, `phase-loop-runtime/scripts/agy_full_pin_scope.sh`, `plans/evidence/qualified-provider-images.json`, `plans/evidence/agy-*-linux-x64-qualification.json`, `.github/workflows/qualified-agy-image.yml`, `.github/workflows/publish-pypi.yml`, `phase-loop-runtime/tests/test_agy_qci.py`, `phase-loop-runtime/tests/test_agy_catalog_data.py`, `phase-loop-runtime/tests/fixtures/agy_validator_corpus/**`, `phase-loop-runtime/tests/test_agy_record_v2.py`, `phase-loop-runtime/tests/test_qualified_agy_image_set.py`, `phase-loop-runtime/tests/test_verify_qualified_agy_route_core.py`, `phase-loop-runtime/tests/test_agy_upstream_advisory.py`, `phase-loop-runtime/tests/test_outside_agent_release_surface.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `load_catalog`; `QUALIFIED_IMAGES` (still a module-level `dict`); `QUALIFICATION_VALIDATOR`; `seat_qci`; the verifier modes `--contract`, `--release --conformance-report` and `--upstream-only`; `convert_agy_record_v2.py --check|--write`; `agy_watch.summarize` (v2); `agy_watch.edit_catalog`; the watch label `agy-qci:<seat_qci>`.
- **Interfaces consumed**: `CONFORMANCE_OBLIGATIONS` (SL-2)
- **Notes**:
  - **Stop gate first (SL-1.1, SL-1.2).**
    - The converter's `--check` mode finds each member's record commit (AGYROLL §3.5). It
      requires two equalities between that commit and head: `agy_profile_digest()`, and the
      validator closure hash (a stdlib AST walk).
    - It runs under the locked env. If it fails, the lane stops and reports: that member
      needs one owner-approved live requalification and an amendment.
    - Nothing else in SL-1 starts before the gate passes.
  - **Runtime (SL-1.3, SL-1.4).**
    - **Loader.** It reads through `importlib.resources` and validates strictly: closed
      keys, hex64 digests, unique images and versions, `routes` == `{"linux-x64"}`, and
      `pinned` a bool. Any failure returns `{}`, never raises at import, and sets
      `CATALOG_STATUS`.
    - **Data file.** Generated from the 1.5.3 literal, with `qci` = `seat_qci()`, and
      `asset_sha256` and `published_at` taken from the record and its release.
    - **Package data.** `pyproject.toml` adds `"data/agy_catalog.json"`.
    - **What stays.** `ROUTE_CORE`, `runtime_identity`, `PROFILE_ID` and
      `agy_profile_digest()` are unchanged.
    - **Semantic guard.** A corpus in `tests/fixtures/agy_validator_corpus/` covers, for
      every pass predicate, a passing case and each failing case. The guard pins
      `{QUALIFICATION_VALIDATOR: sha256(verdict vector)}`.
      - Mutants are monkeypatched into the transitive callees, including
        `panel_invoker.terminal_verdict`. Each must change the vector and fail without a
        literal bump.
      - The converter's closure hash supplements it.
    - **Inventory.** The `gemini_heartbeat.load_catalog` `io.read_text` row is added.
    - **Deselected here.** SL-1.4's verify run deselects the literal-coupled watch and
      verifier tests in `test_agy_self_qualification.py` (`-k "not watch and not
      verifier"`). SL-1.6 rewrites them, and SL-1.7 runs that file in full.
  - **Records, verifier, watch, workflows (SL-1.5, SL-1.6).**
    - **`--contract`.** It parses the catalog strictly, fails on an empty catalog, and runs
      on every PR. The `paths:` filters are removed, because the QCI reads `panel_invoker.py`.
    - **`--release`.** It needs a JUnit report whose obligation ids equal
      `CONFORMANCE_OBLIGATIONS` exactly: each passed once, with none skipped, xfailed or
      errored.
    - **Removed.** `--route-core` and `--source-only`.
    - **`publish-pypi.yml`.** Before the build, with `AGY_CONFORMANCE_STRICT=1`, it runs the
      suite with `--junitxml="$RUNNER_TEMP/agy-conformance/conformance.xml"`, then
      `--release --conformance-report` on that path.
    - **Watch.** `edit_catalog` and the QCI label replace `edit_constants` and
      `route_core_digest`, in code, tests and inventory. `_watch_repo` reads
      `data/agy_catalog.json` and fails, rather than skips, in a repo checkout.
    - **Membership.** `test_qualified_agy_image_set.py` asserts that the runtime set equals
      the data file and the records. It pins no version.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | `tests/test_agy_record_v2.py` (`check` cases) | `--check` finds the record commit; refuses when there is no record commit; refuses on an `agy_profile_digest` or validator-closure mismatch; passes for a converted fixture | `cd phase-loop-runtime && timeout 600 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_agy_record_v2.py -k check` |
| SL-1.2 | impl | SL-1.1 | `scripts/convert_agy_record_v2.py` (`--check`); then the **stop gate** `cd phase-loop-runtime && timeout 600 uv run --locked python scripts/convert_agy_record_v2.py --check` (on failure, stop the lane and report) | — | — |
| SL-1.3 | test | SL-1.2 | `tests/test_agy_qci.py`, `tests/test_agy_catalog_data.py`, `tests/fixtures/agy_validator_corpus/**`, `tests/data/seat_launch_references.json` | **Loader:** missing, malformed, extra-key, duplicate, wrong-route or empty files give `{}` and no release fast path; a data-file member is admitted `release_qualified` offline. **QCI:** `seat_qci()` equals `agy_profile_digest()` at v1; it is unchanged by a `__version__` or catalog edit, and changed by an `OPERATIONS_CONTRACT`, profile or literal edit. **Guard:** each mutant fails it without a bump. **Inventory:** the `load_catalog` row is exact. | `cd phase-loop-runtime && timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_seat_reference_inventory.py` |
| SL-1.4 | impl | SL-1.3 | `gemini_heartbeat.py`, `agy_qualification.py`, `data/agy_catalog.json`, `pyproject.toml`, inventory row; verify with `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_seat_reference_inventory.py tests/test_agy_self_qualification.py -k "not watch and not verifier"` | — | — |
| SL-1.5 | test | SL-1.4 | `tests/test_agy_record_v2.py`, `tests/test_qualified_agy_image_set.py`, `tests/test_verify_qualified_agy_route_core.py`, `tests/test_agy_upstream_advisory.py`, `tests/test_outside_agent_release_surface.py`, `tests/test_agy_self_qualification.py`, `tests/data/seat_launch_references.json` | **`--contract`:** v2 is closed; non-QCI drift passes and QCI drift fails, naming the member; a member with no record fails; an unlisted record is ignored; an empty or malformed catalog fails. **`--release`:** fails with no report, or with a report that has a skipped, xfailed, missing or duplicate obligation, or with an asset mismatch. **Workflows:** no path filter; strict conformance writes to `$RUNNER_TEMP`, then `--release`; no `--source-only` or `--route-core`. **Watch:** `edit_catalog` edits only the data file; `_watch_repo` does not skip; the inventory is exact. | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_record_v2.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_outside_agent_release_surface.py tests/test_agy_self_qualification.py tests/test_seat_reference_inventory.py` |
| SL-1.6 | impl | SL-1.5 | converter `--write`, verifier, `agy_watch.py`, evidence, both workflows, inventory, deletions | — | — |
| SL-1.7 | verify | SL-1.6 | SL-1 owned files | all SL-1 tests, plus the verifier on the real evidence | `cd phase-loop-runtime && timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_qci.py tests/test_agy_catalog_data.py tests/test_agy_record_v2.py tests/test_qualified_agy_image_set.py tests/test_verify_qualified_agy_route_core.py tests/test_agy_upstream_advisory.py tests/test_outside_agent_release_surface.py tests/test_agy_static_integrity.py tests/test_agy_integrity_seat_admission.py tests/test_gemini_heartbeat_bootstrap.py tests/test_agy_self_qualification.py tests/test_seat_reference_inventory.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract` |

### SL-2 — Strict hermetic route conformance suite
- **Scope**: Prove in CI, with no provider, that the production qualification driver meets every pass predicate. This is the harness-side guarantee the full pin stood in for, and it cannot pass by skipping.
- **Owned files**: `phase-loop-runtime/tests/test_agy_route_conformance.py`, `phase-loop-runtime/tests/fixtures/agy_conformance/**`
- **Interfaces provided**: `CONFORMANCE_OBLIGATIONS`, `IF-0-RECBIND-2`
- **Interfaces consumed**: `qualify_image` (pre-existing), `run_operation` (pre-existing) and the validator path, all read-only
- **Notes**:
  - **Stand-in.** It speaks the stream-json surface implied by the redacted `records[]`
    shape, with no raw receipt.
  - **Operations.** `completion`, `cancel` and `owner-loss` run through `qualify_image`
    under the real profile and seal checks.
  - **Mutants.** Each must fail its operation:
    - one emits no terminal event;
    - one ignores cancel;
    - one leaves an orphaned child.
  - **Strict mode.** With `AGY_CONFORMANCE_STRICT=1`, a missing bwrap or user namespace is
    `pytest.fail`, and every obligation is a parametrized case with its id in
    `CONFORMANCE_OBLIGATIONS`.
  - **Hard stop.** If the driver cannot run hermetically, stop and report an amendment
    (Assumption 3). Never mock the driver.
- **Tasks**:

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | `tests/test_agy_route_conformance.py`, `tests/fixtures/agy_conformance/**` | Three operations pass with the conforming stand-in. Each mutant fails. Strict mode fails on a missing bwrap or user namespace. The obligation ids equal `CONFORMANCE_OBLIGATIONS`. | `cd phase-loop-runtime && AGY_CONFORMANCE_STRICT=1 timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_route_conformance.py` |
| SL-2.2 | impl | SL-2.1 | stand-in, mutants, strict-mode hook | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests, with the report in a private run directory | `cd phase-loop-runtime && RUN_DIR="$(mktemp -d)" && AGY_CONFORMANCE_STRICT=1 timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_route_conformance.py --junitxml="$RUN_DIR/conformance.xml"` |

### SL-3 — Documentation & spec reconciliation (SL-docs)

- **Scope**: Refresh the docs catalog, update the docs this phase invalidated, and append amendments.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`, `docs/advisor-board-capabilities-card.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `specs/phase-plans-agyroll-v1.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal)
- **Depends on**: SL-1, SL-2

**Tasks**:

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-3.1 | docs | — | `.claude/docs-catalog.json` | Rescan with the scaffold helper when present; otherwise record "manual catalog audit". |
| SL-3.2 | docs | SL-3.1 | per catalog | **CONTRACTS** ("qualified images"): package data, record v2, strict release gate. **Release handoff:** drop "live requalification of every listed member". **Capabilities card:** gate wording. **agy-upstream-watch:** `edit_catalog` and the QCI label. **CHANGELOG:** add an entry. |
| SL-3.3 | docs | SL-3.2 | `specs/phase-plans-agyroll-v1.md` | Append `### Post-execution amendments` if a freeze proved wrong. |
| SL-3.4 | verify | SL-3.3 | — | No doc linter is configured. Re-run `timeout 120 uv run --locked python -m phase_loop_runtime.roadmap_lint specs/phase-plans-agyroll-v1.md`. |

## Execution Notes

- **Single-writer files**:
  - SL-1: every runtime, record, verifier, watch, workflow and inventory file listed above.
  - Later phases:
    - PROVFWD takes `agy_watch.py` and the verifier's `--upstream-only` fetch;
    - REQUAL takes `agy_qualification.py`;
    - ROLLJOB takes the verifier and `agy_watch.py` after PROVFWD.
- **Known destructive changes**:
  - `phase-loop-runtime/scripts/agy_full_pin_scope.sh` and `plans/evidence/qualified-provider-images.json` are deleted.
  - `source_sha256` is removed from member records.
  - The `--route-core` and `--source-only` paths are removed from `verify_qualified_agy_image.py`.
  - The `paths:` filters are removed from `qualified-agy-image.yml`.
- **Expected add/add conflicts**: none. Only the `plans/manifest.json` tail conflicts with agent-harness#1925 and agent-harness#1926. Rebase and re-append.
- **No release dispatch.** This phase dispatches no release. The first cut that uses `--release` is EC-ACTIVATE-3.
- **Lockfile.** `uv.lock` should stay unchanged. It is owned only so that a resolver rewrite cannot leave an unowned dirty path.
- **Merge order.** SL-2, then SL-1 (its stop gate SL-1.2 first), then SL-3.
- **Shared host.** Run targeted pytest serially, under `timeout`, with reports in private run directories. Strict conformance and `--release` gate in CI. There is no live run and no `ai` access.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- SL-1: effort=high, reason=release gate and evidence migration and semantic guard are security-relevant
- SL-2: effort=high, reason=hermetic driver harness under bwrap in strict mode
- SL-3: effort=low, reason=docs sweep only

## Acceptance Criteria

- [ ] EC-RECBIND-1 — Proven by `tests/test_agy_catalog_data.py` and `tests/test_agy_record_v2.py`. Falsified by a malformed `data/agy_catalog.json` admitting any image through `gemini_heartbeat.admit`, or by an empty catalog passing `--contract`.
- [ ] EC-RECBIND-2 — Proven by `tests/test_agy_qci.py`. Falsified by a verdict-changing validator mutant, including one in `panel_invoker.terminal_verdict`, passing the guard without a `QUALIFICATION_VALIDATOR` bump; or by a `__version__` bump or a catalog edit changing `seat_qci()`.
- [ ] EC-RECBIND-3 — Proven by `tests/test_agy_record_v2.py`, `tests/test_verify_qualified_agy_route_core.py` and `uv run --locked python scripts/verify_qualified_agy_image.py --contract`. Falsified by a record whose `qci` differs from the tree's passing `--contract`, or by a PR outside the old path filter not running `--contract`.
- [ ] EC-RECBIND-4 — Proven by `AGY_CONFORMANCE_STRICT=1 pytest tests/test_agy_route_conformance.py`. Falsified by any predicate mutant passing its operation through the production `qualify_image`.
- [ ] EC-RECBIND-5 — Proven by `tests/test_verify_qualified_agy_route_core.py` (workflow wiring) and `tests/test_agy_record_v2.py` (non-QCI drift passes; QCI drift fails). Falsified by any of:
  - a skipped conformance run passing `--release`;
  - a report with a skipped, xfailed or missing obligation passing `--release`;
  - `publish-pypi.yml` still invoking `--source-only`;
  - an `OPERATIONS_CONTRACT` edit passing `--release`.
- [ ] EC-RECBIND-6 — Proven by `tests/test_agy_record_v2.py` and `uv run --locked python scripts/convert_agy_record_v2.py --check`. Falsified by the converter accepting a record with no record commit, or one whose record-commit `agy_profile_digest()` or validator closure differs from head's.

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
timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract
# CI / Gate A only:
RUN_DIR="${RUNNER_TEMP:-$(mktemp -d)}/agy-conformance" && mkdir -p -m 0700 "$RUN_DIR"
AGY_CONFORMANCE_STRICT=1 timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_route_conformance.py --junitxml="$RUN_DIR/conformance.xml"
timeout 600 uv run --locked python scripts/verify_qualified_agy_image.py --release \
  --conformance-report "$RUN_DIR/conformance.xml"
```

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/releases/outside-agent-release-handoff.md`, `docs/ops/agy-upstream-watch.md`, `docs/advisor-board-capabilities-card.md`
- evidence paths: `plans/evidence/agy-*-linux-x64-qualification.json`
- redaction posture: `metadata_only`
- downstream handling: none
