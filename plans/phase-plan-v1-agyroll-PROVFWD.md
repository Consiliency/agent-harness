---
phase_loop_plan_version: 1
phase: PROVFWD
roadmap: specs/phase-plans-agyroll-v1.md
roadmap_sha256: 07b8fc36798ec943f7d83037aa30574fd82677b9292238e9ceb89112a0a54a64
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_provenance_forward.py tests/test_agy_attestation.py tests/test_agy_provenance_wiring.py tests/test_agy_self_qualification.py tests/test_agy_upstream_advisory.py tests/test_agy_record_v2.py tests/test_agy_size_bounds.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py && timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract"]
---

# PROVFWD: Forward provenance for any stable release

## Context

PROVFWD removes the count-based recency window. Today `agy_provenance.find_provenance`
examines only the newest `RECENCY_WINDOW = 4` stable releases, so a host that falls behind
can never prove where its image came from. The phase replaces the window with a forward
lookup over every listed stable release, bounded by a per-call download budget and a daily
total cap, and it records attestation status (R4, R5).

**Frozen inputs.**
- AGYROLL §1 and §8 (`plans/artifacts/agyroll-v1-contract.md`): the design.
- AGYFRESH §1.1 (`plans/artifacts/agyfresh-contract.md`): the archive bounds the resolver
  reads at call time.
- `plans/artifacts/agyroll-PROVFWD-detail.md` (PROVFWD-detail): symbols, per-file changes and
  test cases. It is read-only during execution.

Both contracts are pinned by sha256 in the roadmap's External Inputs.

**Revision 2 (2026-11-20).** It applies the independent review and the coordinator's
rulings: the daily cap is enforced on the production route from this phase onward, and the
second-channel measurement is authorized within PROVFWD-detail §2.2's bounds.

**Revision 3 (2026-11-20).** The fetch ledger is keyed on the store and the image only, as R4
states it, and is shared across profiles (PROVFWD-detail §1.3).

**Prerequisites.**
- RESTORE's caps lane is merged (it is: agent-harness#2017). PROVFWD does not wait for
  EC-RESTORE-1, which is operational evidence.
- HOLD's core lane is merged before SL-5 starts, because it rewrites the first-use path that
  SL-5 wires. SL-1 to SL-3 do not wait for it.

```
RECBIND ──> RESTORE caps lane ──(merged)──> PROVFWD SL-1..SL-3 ─┐
            HOLD core lane ─────(merged)──────────────────────> PROVFWD SL-5 ──> merge
            RESTORE restore runs (EC-RESTORE-1): not a prerequisite
```

**Delivery boundary.** The phase is one pull request, and it does not merge without SL-5.
The resolver never reaches `main` with an empty fetch ledger on the production route. This
amends the roadmap's split, which kept `agy_qualification.py` out of PROVFWD; the amendment
text and its reason are frozen in PROVFWD-detail §6 and applied by SL-4. That section also
amends two sentences of AGYROLL §1.2 (the ledger's key and the ordering exception). The alternative,
landing REQUAL's cap piece first, does not avoid the edit: the first-use call site must pass
the ledger to the new resolver in the same change that removes the window.

**Stop rules.**
- If `tests/test_agy_qci.py`'s verdict-vector pin changes, the lane stops and reports
  (AGYFRESH §3). Only its source-hash supplement may be updated, as a reviewed change.
- The second-channel comparison basis is measured and frozen before SL-2 starts
  (PROVFWD-detail §2.2). If neither basis holds, SL-1 stops and reports.
- SL-5 edits only what PROVFWD-detail §1.3 lists. If the landed first-use stage cannot carry
  it without changing a hold-eligibility rule, SL-5 stops and reports.
- A lane that needs to edit `gemini_heartbeat.py`, `panel_invoker.py`, or any validator
  function named in AGYFRESH §3 stops and reports.

## Interface Freeze Gates

- [ ] IF-0-PROVFWD-1 — AGYROLL §1, with the symbols frozen in PROVFWD-detail §1.1 and §2.1:
  - `find_provenance(…, hint, budget, fetch_times, note_fetch, attest, now)` with no `window`;
  - `stable_releases(transport, *, limit=None)` and `version_hint(subject_path)`;
  - `ProvenanceError.reason` and the reasons `budget_exhausted` and `download_cap_reached`;
  - `Provenance.attestation` and `Provenance.second_channel`;
  - `agy_attestation.attestation_status`, `second_channel_status`, the two status
    vocabularies and the code `agy_provenance_second_channel_mismatch`;
  - the `fetch_ledger` store entry keyed on `(image, platform)`, `Store.fetch_times`,
    `note_fetch`, `rejected_assets`, `note_rejected`, and the `on_retryable` keyword
    (PROVFWD-detail §1.3);
  - the candidate-order exception for rejected assets (PROVFWD-detail §1.2).

## Lane Index & Dependencies

SL-1 — Attestation and second channel
  Depends on: (none)
  Blocks: SL-2, SL-3, SL-4
  Parallel-safe: yes

SL-2 — Resolver and watch listing
  Depends on: SL-1
  Blocks: SL-4, SL-5
  Parallel-safe: yes

SL-3 — Verifier upstream fetch and status vocabulary
  Depends on: SL-1
  Blocks: SL-4
  Parallel-safe: yes

SL-4 — Documentation & spec reconciliation
  Depends on: SL-1, SL-2, SL-3, SL-5
  Blocks: (none)
  Parallel-safe: no

SL-5 — Store ledger and seat call-site wiring
  Depends on: SL-1, SL-2
  Blocks: SL-4
  Parallel-safe: no

SL-2 and SL-3 run in parallel after SL-1. SL-5 is serialized behind HOLD's core lane. The roadmap names resolver, attestation and
callers as lanes. The watch's listing call moves into the resolver lane because removing
`window` breaks that call in the same change, and the lane-IR check refuses a file owned by
two lanes.

## Lanes

### SL-1 — Attestation and second channel
- **Scope**: Add the attestation query and the catalog-job second-channel check as a new module with its own pinned opener.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_attestation.py`, `phase-loop-runtime/tests/test_agy_attestation.py`
- **Interfaces provided**: `attestation_status`, `second_channel_status`, `ATTESTATION_STATUSES`, `SECOND_CHANNEL_STATUSES`, `SECOND_CHANNEL_MISMATCH`
- **Interfaces consumed**: `agy_provenance._trust_context`, `ProvenanceError`, `UNAVAILABLE`, `USER_AGENT`, `ReleaseAsset`, `read_member` (pre-existing)
- **Parallel-safe**: yes
- test: PROVFWD-detail §4.3, written first and failing.
- impl: PROVFWD-detail §2. Measure the comparison basis (SL-1.1) before implementing it.
- verify: the lane's test file plus `tests/test_agy_qci.py`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | (none) | `phase-loop-runtime/tests/test_agy_attestation.py` | PROVFWD-detail §4.3 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_attestation.py` |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_attestation.py` | (none) | same |
| SL-1.3 | verify | SL-1.2 | `phase-loop-runtime/tests/test_agy_attestation.py` | PROVFWD-detail §4.3 | same, plus `tests/test_agy_qci.py` |

### SL-2 — Resolver and watch listing
- **Scope**: Replace the recency window with the budgeted forward resolver, and move the watch to the unwindowed listing and the recorded statuses.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py`, `phase-loop-runtime/tests/test_agy_provenance_forward.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py`
- **Interfaces provided**: `find_provenance`, `version_hint`, `stable_releases`, `ProvenanceError.reason`, `Provenance.attestation`; `agy_watch.summarize(…, attestation, second_channel)`
- **Interfaces consumed**: `attestation_status`, `second_channel_status`, `SECOND_CHANNEL_MISMATCH` (SL-1); the three size bounds of IF-0-RESTORE-1 (pre-existing)
- **Parallel-safe**: yes
- test: PROVFWD-detail §4.1 and §4.2, written first and failing.
- impl: PROVFWD-detail §1.1, §1.2 and §3.1.
- verify: both test files, `tests/test_agy_size_bounds.py` and `tests/test_agy_qci.py`. The inventory test is run by SL-5.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | (none) | `phase-loop-runtime/tests/test_agy_provenance_forward.py`, `phase-loop-runtime/tests/test_agy_self_qualification.py` | PROVFWD-detail §4.1, §4.2 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_provenance_forward.py tests/test_agy_self_qualification.py` |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py` | (none) | same |
| SL-2.3 | impl | SL-2.2 | `phase-loop-runtime/src/phase_loop_runtime/agy_watch.py` | (none) | same |
| SL-2.4 | verify | SL-2.3 | the lane's test files | PROVFWD-detail §4.1, §4.2 | same, plus `tests/test_agy_size_bounds.py tests/test_agy_qci.py` |

### SL-3 — Verifier upstream fetch and status vocabulary
- **Scope**: Make `--upstream-only` pick the newest stable release from the listing, and close the record's two status vocabularies.
- **Owned files**: `phase-loop-runtime/scripts/verify_qualified_agy_image.py`, `phase-loop-runtime/tests/test_agy_upstream_advisory.py`, `phase-loop-runtime/tests/test_agy_record_v2.py`
- **Interfaces provided**: `newest_stable(fetch)`; `latest_published_at` in the `--upstream-only` result
- **Interfaces consumed**: `ATTESTATION_STATUSES`, `SECOND_CHANNEL_STATUSES` (SL-1)
- **Parallel-safe**: yes
- test: PROVFWD-detail §4.4, written first and failing.
- impl: PROVFWD-detail §3.2. The verifier keeps exactly its three modes.
- verify: both test files, `tests/test_verify_qualified_agy_route_core.py` and `--contract`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | (none) | `phase-loop-runtime/tests/test_agy_upstream_advisory.py`, `phase-loop-runtime/tests/test_agy_record_v2.py` | PROVFWD-detail §4.4 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_upstream_advisory.py tests/test_agy_record_v2.py` |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/scripts/verify_qualified_agy_image.py` | (none) | same |
| SL-3.3 | verify | SL-3.2 | the lane's test files | PROVFWD-detail §4.4 | same, plus `tests/test_verify_qualified_agy_route_core.py`, then `timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract` |

### SL-4 — Documentation & spec reconciliation
- **Scope**: Update the docs this phase invalidates, after every code lane.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/ops/agy-upstream-watch.md`, `CHANGELOG.md`, `.claude/docs-catalog.json`, `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyroll-v1-contract.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Action |
|---|---|---|---|---|
| SL-4.1 | docs | — | `.claude/docs-catalog.json` | Rescan with the scaffold helper when present; otherwise record "manual catalog audit". |
| SL-4.2 | docs | SL-4.1 | the three docs | **CONTRACTS** (self-qualification): forward lookup, budget, cap, reasons, hint, attestation, the second-channel basis and that `not_listed` is not corroboration, the fetch ledger, and the GitHub API as a first-use dependency. **Watch runbook:** no window; `--version` takes any listed stable release; the two statuses. **CHANGELOG:** one entry. |
| SL-4.3 | docs | SL-4.2 | `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyroll-v1-contract.md` | Apply PROVFWD-detail §6 verbatim; recompute the AGYROLL digest in External Inputs from the committed file; then `timeout 120 uv run --locked python -m phase_loop_runtime.roadmap_lint specs/phase-plans-agyroll-v1.md`. |
| SL-4.4 | verify | SL-4.3 | — | `grep -rn "RECENCY_WINDOW\|recency window\|in-window" docs phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` returns nothing outside history. |

### SL-5 — Store ledger and seat call-site wiring
- **Scope**: Persist the fetch ledger in the store, keyed on the store and image, and wire the hint, the ledger and the retryable release into the one first-use call site.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/tests/test_agy_provenance_wiring.py`, `phase-loop-runtime/tests/data/seat_launch_references.json`
- **Interfaces provided**: `Store.fetch_times`, `Store.note_fetch`, `Store.rejected_assets`, `Store.note_rejected`, `on_retryable`
- **Interfaces consumed**: `find_provenance`, `version_hint` (SL-2); `admit_seat` (pre-existing); the first-use stage of IF-0-HOLD-1 (pre-existing), both once HOLD's core lane merges
- **Parallel-safe**: no
- test: PROVFWD-detail §4.5, written first and failing, through the real `requalify_once`.
- impl: PROVFWD-detail §1.3 and §5.
- verify: the lane's test file, `tests/test_agy_self_qualification.py`, `tests/test_agy_hold.py`, `tests/test_agy_qci.py` and the inventory test.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-5.1 | test | (none) | `phase-loop-runtime/tests/test_agy_provenance_wiring.py` | PROVFWD-detail §4.5 | `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 600 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_agy_provenance_wiring.py` |
| SL-5.2 | impl | SL-5.1 | `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/tests/data/seat_launch_references.json` | (none) | same |
| SL-5.3 | verify | SL-5.2 | `phase-loop-runtime/tests/test_agy_provenance_wiring.py` | PROVFWD-detail §4.5 | same, plus `tests/test_agy_self_qualification.py tests/test_agy_hold.py tests/test_agy_qci.py tests/test_seat_reference_inventory.py` |

## Execution Notes

- **One PR.** The phase lands as one pull request; lanes are its internal ownership units. It merges only with SL-5 in it.
- **Shared append-only files.** `CONTRACTS.md`, `CHANGELOG.md` and
  `tests/data/seat_launch_references.json` are also touched by HOLD's lanes. Each phase adds
  its own section or rows; the PR that merges second rebases and reconciles, never rewriting
  the other's text. `tests/test_agy_self_qualification.py` is also edited by REQUAL's early
  slice, with the same rule.
- **Single-writer order.** `agy_provenance.py`, `agy_watch.py` and the verifier pass to
  ROLLJOB when this phase merges. `agy_qualification.py` passes from HOLD to SL-5, then to
  REQUAL; REQUAL's early slice edits other functions and rebases over SL-5 or the reverse.
- **Shared host.** Targeted pytest only, serial (no `-n`), under `timeout`. No full suite, no
  `-n auto`, no live provider call. Full pytest, strict conformance and `--release` run in
  hosted CI on the PR.
- **Network.** Tests use fake transports. The one measurement in SL-1.1 is authorized
  (coordinator, 2026-11-20) within PROVFWD-detail §2.2's bounds: public unauthenticated
  reads, nothing executed. It is not a provider call.
- **Requalification.** None intended (AGYFRESH §3).
- **Rollback.** Revert. Hosts return to the four-release window; no store migration, because
  the store's entries and keys do not change.
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Execution Policy

- SL-1: effort=medium, reason=new module with a pinned opener and a measured basis
- SL-2: effort=high, reason=admission-path resolver and budget accounting
- SL-3: effort=medium, reason=bounded verifier change
- SL-4: effort=low, reason=docs sweep and a frozen roadmap amendment
- SL-5: effort=high, reason=admission-path store and retry wiring

## Acceptance Criteria

Test files are under `phase-loop-runtime/`.

- [ ] EC-PROVFWD-1 — proven by `tests/test_agy_provenance_forward.py` (PROVFWD-detail §4.1 cases 1–2) and `tests/test_agy_provenance_wiring.py` (case 1); falsified by restoring a slice of the listing in `find_provenance`.
- [ ] EC-PROVFWD-2 — proven by `tests/test_agy_provenance_forward.py` (cases 3–4, 8) and, on the shipped route through `requalify_once`, `tests/test_agy_provenance_wiring.py` (cases 2–6a); falsified by a thirteenth fetch inside 24 h through `requalify_once` for one store and image under any mix of profiles, by a third fetch in one call, by a fetch after twelve inside 24 h, or by a second call that re-fetches a cached member.
- [ ] EC-PROVFWD-3 — proven by `tests/test_agy_provenance_forward.py` (cases 5–6); falsified by `version_hint` opening the subject, or by a hint admitting a non-matching digest.
- [ ] EC-PROVFWD-4 — proven by `tests/test_agy_attestation.py` and `tests/test_agy_provenance_forward.py` (case 9); falsified by an empty `attestations` list returning a status instead of `unavailable`, or by `second_channel` other than `not_checked` outside the watch.
- [ ] EC-PROVFWD-5 — proven by `tests/test_agy_self_qualification.py` and `tests/test_agy_size_bounds.py` with the §1.1 tests unmodified; falsified by any edit to those tests' assertions.
- [ ] EC-PROVFWD-6 — proven by `tests/test_agy_self_qualification.py` (watch cases) and `tests/test_agy_provenance_forward.py` (case 11); falsified by any `RECENCY_WINDOW` or `window=` remaining in `agy_*.py`.
- [ ] Plan-internal (inventory) — proven by `tests/test_seat_reference_inventory.py`; falsified by a new `io.open` site in `agy_attestation.py` with no row.
- [ ] Plan-internal (QCI) — proven by `tests/test_agy_qci.py`; falsified by a changed verdict-vector pin in this phase's diff.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_agy_provenance_forward.py tests/test_agy_attestation.py \
  tests/test_agy_provenance_wiring.py tests/test_agy_hold.py \
  tests/test_agy_self_qualification.py tests/test_agy_upstream_advisory.py \
  tests/test_agy_record_v2.py tests/test_agy_size_bounds.py \
  tests/test_verify_qualified_agy_route_core.py tests/test_agy_qci.py \
  tests/test_seat_reference_inventory.py
timeout 300 uv run --locked python scripts/verify_qualified_agy_image.py --contract
```

Hosted CI on the PR: the seven required checks, the `agy catalog contract` job, and the
strict conformance run with `--release` (the commands at the end of the roadmap's
Verification section). SL-4 touches `docs/`, so dispatch Gate A as `CONTRIBUTING.md`
describes.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `docs/ops/agy-upstream-watch.md`, `specs/phase-plans-agyroll-v1.md`, `plans/artifacts/agyroll-v1-contract.md`
- evidence paths: `phase-loop-runtime/tests/test_agy_provenance_forward.py`
- redaction posture: `metadata_only`
- downstream handling: roadmap amendment (PROVFWD-detail §6); plans that pin the roadmap digest regenerate it after this phase merges
