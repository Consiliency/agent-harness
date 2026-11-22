# Phase roadmap JEVHOST v1: the JEV Drill host adapter on `main`

> # ADVISORY — not runner-selected (2026-11-22)
>
> This roadmap is planned and landed manually while `specs/phase-plans-v11.md` remains the
> sole active runner-selected roadmap. It grants no live run, no provider call and no access
> to any host.

## Context

The owner assigned the sanitized draft agent-harness#2071, the discovery-aware JEV Drill
host adapter, to this repository on 2026-11-22. The goal is a merged state on `main`. The
JEV Drill project (`Consiliency/jevdrill`) will pin one accepted `main` commit of this
repository by its full SHA, under conditions R1 to R6 (JEVHOST §1). The draft is one
commit on a September base, far behind `main`, and conflicts in five files. Its contract
copies are older than jevdrill's.

## Architecture North Star

An explicit, default-disabled adapter lets a caller route harness launches through a
separately installed JEV Drill. With no adapter, every harness path behaves exactly as on
`main`. The integration is proven on GitHub's hosted runners alone.

## Assumptions

- A1. The installed-JEV tests can run against jevdrill's public checkout on a hosted
  runner with no secret. If that is false, R3's installed-JEV leg is disclosed as not
  done (JEVHOST §8).

## External Inputs

| Input | Pin |
| --- | --- |
| JEVHOST contract | `plans/artifacts/jevhost-v1-contract.md`, sha256 `0c6a44e19f1909933dc664ab0d944c62b9320428132c5bf3796a542f85efe892` |
| Draft commit | agent-harness#2071 head `784d1595a08f42519862ae5f9336f20186d83c4b`, base `56dce95a52625a58cd08911f8f623c637bf52e44` |
| jevdrill contract commit | `Consiliency/jevdrill` `998912b1e0195464e6f3aa048c5421c2bed57491` (JEVHOST §5 SHA rule) |

These are immutable planning inputs. A change needs a reviewed repin. No plan pins a
future implementation commit, a commit count or a landing topology.

## External Readiness Gates

- **EXT-JEV.** jevdrill `main` stays at or after the pinned commit. A change to its
  `schemas/` or the three fixtures before the merge triggers the re-sync rule of JEVHOST §5.
- **EXT-WRITERS.** K-1 SL-6 (agent-harness#2082) also writes
  `tests/data/seat_launch_references.json`. Whichever lands second rebases and
  regenerates its own rows. The OI-1 fence lane and agent-harness#2081 write no file of
  this phase (JEVHOST §11).
- **EXT-JEVQ.** Two questions are open with JEV Drill: acceptance of the
  `jevdrill_installed` marker, and the exact Python 3.14 target. Each has a stated
  fallback (JEVHOST §14), so neither blocks execution.

## Non-Goals

- Any change to jevdrill, its workflows or its records.
- Any live JEV Drill run, provider call, model call, study or spend.
- Making the new companion workflow a required check.
- The October evidence receipts and handoffs (dropped, JEVHOST §9).

## Cross-Cutting Principles

- **Default-off.** With no adapter, `main`'s behaviour is preserved and its tests keep
  their assertions.
- **No weakened gate.** No existing required check, `-m` expression or job changes.
- **Public only.** No secret, no private repository, no host name, no local path.
- **Shared-host test limits.** Targeted pytest files, serially without `-n`, under
  `timeout`. Full suites go to hosted CI or Gate A.

## Top Interface-Freeze Gates

- IF-0-JEVHOST-1 — The path-scoped replay, the hunk resolutions and the semantic rules (JEVHOST §2 to §4).
- IF-0-JEVHOST-2 — The contract copies at the named jevdrill commit (JEVHOST §5).
- IF-0-JEVHOST-3 — Test selection, the `jevdrill_installed` marker and the R5 names (JEVHOST §6, §7).
- IF-0-JEVHOST-4 — The companion workflow, the sync command and the CI Python (JEVHOST §8).

## Phases

### Phase 1 — JEV Drill host adapter on main (JEVHOST)

**Objective**

`main` holds the draft's adapter, portability modules and twelve test files, reconciled
with current `main`. Its contract copies are jevdrill's, and its tests pass on hosted Linux,
so jevdrill can pin one accepted commit.

**Exit criteria**

- [ ] EC-JEVHOST-1 — (R1) A `main` commit, merged under this repository's required checks, holds the five modules, the twelve files and their helpers, `tests/fixtures/jevdrill/`, and a `pyproject.toml` and `uv.lock` for which `uv sync --locked` succeeds; the excluded paths of JEVHOST §9 are absent.
- [ ] EC-JEVHOST-2 — (R2) The 14 schema copies are byte-identical to jevdrill's at the commit the pull request names, the 3 fixtures equal jevdrill's after the JEVHOST §5 substitution, and `digests.json` recomputes.
- [ ] EC-JEVHOST-3 — With no adapter, `main` behaviour is preserved under JEVHOST §2, and the semantic rules S1 to S6 of JEVHOST §4 hold.
- [ ] EC-JEVHOST-4 — (R3) The twelve files pass, with the installed-JEV tests not skipped, in the companion workflow on hosted Linux at the merge commit. The dispatched macOS, Windows and Python 3.14 legs are run once, and any leg not done or failing is disclosed.
- [ ] EC-JEVHOST-5 — (R4) jevdrill's eight named controls (JEVHOST §1) are collected and selected under `-m "not dotfiles_integration"`; none of them, and no test in the seven R4 files, carries `dotfiles_integration`; exactly the four installed controls carry `jevdrill_installed`, per test and never by module (or, under JEVHOST §14 Q1's fallback, are the four fixture-keyed deselections); and no selected test needs a secret or a private repository.
- [ ] EC-JEVHOST-6 — (R5) Every R5 name imports at the merge commit; there is no rename.
- [ ] EC-JEVHOST-7 — (R6) The pull request states the sync command and the CI Python, and the dispatched matrix runs that command on hosted Linux, macOS and Windows.
- [ ] EC-JEVHOST-8 — The outgoing diff passes `gitleaks` and the disclosure grep of JEVHOST §9, and no existing required check is weakened.

**Scope notes**

Decompose into six lanes with disjoint ownership, each bringing in only its own draft
paths (JEVHOST §2): portability modules, contract copies and the companion workflow in
parallel first; then the launcher; then the adapter and runner; then a docs reducer.

**Non-goals**

Everything under Non-Goals above.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/{jevdrill_adapter,jevdrill_queue,runner,launcher,observability}.py`
- `phase-loop-runtime/src/phase_loop_runtime/{file_lock,windows_process,windows_storage,dispatch_lock,agy_qualification,agy_provenance,phase_worktree_executor,prompts}.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/{event_log,fencing}.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`
- `phase-loop-runtime/tests/fixtures/jevdrill/**`
- `phase-loop-runtime/tests/conftest.py`
- `phase-loop-runtime/pyproject.toml`
- `phase-loop-runtime/tests/data/seat_launch_references.json`
- `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`
- `.github/workflows/jevdrill-companion.yml`
- `docs/jevdrill-integration.md`

**Depends on**

- (none)

**Produces**

- IF-0-JEVHOST-1 — Replay, hunk resolutions and semantic rules.
- IF-0-JEVHOST-2 — Contract copies at the named jevdrill commit.
- IF-0-JEVHOST-3 — Test selection and R5 names.
- IF-0-JEVHOST-4 — Companion workflow, sync command and CI Python.

**Spec closeout policy**

schema: `spec_delta_closeout.v1`; expected decision: `canonical_spec_update`;
target surfaces: `docs/jevdrill-integration.md`, `CHANGELOG.md`;
evidence paths: `phase-loop-runtime/tests/test_jevdrill_selection.py`;
`redaction_posture: metadata_only`; missing or malformed evidence routes non-human
`blocker_class=contract_bug`.

## Phase Dependency DAG

```
JEVHOST: {portability, contract, workflow} ──> launcher ──> adapter+runner ──> docs
```

## Execution Notes

- **Planning.** `plans/phase-plan-v1-jevhost-JEVHOST.md`.
- **One integration pull request** from a branch cut from `main`. agent-harness#2071 is
  closed as superseded when it merges.

## Acceptance Criteria

- [ ] Every EC-JEVHOST exit criterion is met, or recorded as unmet with its reason.
- [ ] The merge commit's full SHA, the synced jevdrill SHA, the sync command and the CI
  Python are reported to the JEV Drill executive through Root.

## Verification

```bash
cd phase-loop-runtime
PYTHONPATH=$PWD/src:$PWD/tests timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider \
  -m "not dotfiles_integration" tests/test_jevdrill_selection.py \
  tests/test_jevdrill_adapter.py tests/test_jevdrill_queue.py tests/test_jevdrill_input.py
```
