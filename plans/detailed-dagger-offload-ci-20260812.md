# Detailed plan: offload agent-harness heavy CI to tailnet host `ai` via dagger-offload

**Status: DRAFT — do not land before agent-harness#477 merges. Depends conceptually on the single-lane plan (land that first so the offloaded work is already minimized).**

## Task
Port agent-harness's billed Blacksmith jobs onto the proven `Consiliency/ci-actions/dagger-offload` composite action so heavy CI runs on the maintainer's `ai` rig at ~zero marginal cost. agent-harness is the only heavy Consiliency repo not migrated (gp, fractal-agents, message-board, spec went live 2026-07-02/03).

## Research summary
Reference implementation: `governed-pipeline/.github/workflows/test.yml` uses `Consiliency/ci-actions/dagger-offload@51f62fbc…` with inputs `command`, `eligible` (trust-gate step output), `remote-host: ai`, `ts-authkey: ${{ secrets.TS_AUTHKEY }}`. The action is fail-closed (ai unreachable → job red, never silent fallback to hosted). The org-wide `TS_AUTHKEY` secret (visibility:all) already covers this repo. `ai` runs rootless Docker (user `ci-docker`) + Dagger v0.21.7 with lingering enabled. Trust gate: offload only on push-to-main or same-repo PRs with the secret present — never fork PRs (repo is public; fork PRs keep hosted runners or are skipped per the established pattern).

## Changes

### `.github/workflows/test.yml` (modify)
- pytest matrix job — wrap suite execution in the dagger-offload composite, mirroring gp's `elig` step + `uses:` block; keep a hosted fallback ONLY as an explicitly separate lane if the maintainer wants one (default: fail-closed, no fallback) — reason: move ~90% of billed minutes to ai
- Gate A job — same treatment; the clean-room script already runs in an isolated venv and is Linux-only, which fits Dagger's container model — reason: the heaviest single job
- python-version matrix — reproduce via container images in the Dagger function (3.10/3.11/3.12) — reason: preserve the matrix guarantee off-host

### `dagger/` or `ci/dagger/` (create)
- a minimal Dagger module/function that: checks out the given SHA, installs the package per lane spec, runs the exact pytest/gate commands currently in the workflow — reason: the composite's `command` needs a `dagger call` target; mirror gp's module layout

### `.github/workflows/{docs-audit,scrub,release-consistency,skills-parity}.yml` (defer)
- leave on Blacksmith for now — sub-minute jobs; migration cost exceeds their bill — reason: scope discipline

## Documentation impact
- `CHANGELOG.md` — add — CI execution moved to tailnet offload for heavy lanes
- `docs/` CI notes if any exist — verify none reference Blacksmith-only behavior

## Dependencies & order
1. agent-harness#477 merged (hard gate)
2. Single-lane plan landed (minimizes what gets ported)
3. This plan: Dagger module first, then workflow wiring, one lane at a time (pytest matrix, then Gate A)

## Verification
- Same-repo PR: jobs run on ai (job log shows the tailnet join + `DOCKER_HOST=ssh://ai`), results equal a hosted baseline run on the same SHA
- Kill-switch check: with `TS_AUTHKEY` removed in a test context, job goes red (fail-closed), not silently hosted
- Fork-PR simulation: `eligible=false` path keeps the job off ai

## Acceptance criteria
- [ ] pytest matrix + Gate A execute on ai for same-repo PRs and main pushes, green on a real candidate SHA
- [ ] Fail-closed proven (unreachable/no-secret → red, no hosted fallback)
- [ ] Billed Blacksmith minutes for a representative push drop to the sub-minute jobs only
- [ ] Fork-PR path never receives the tailnet key

## Generalizability note (for GOVLEAN, not this plan)
This plan is fleet-internal. The client-facing story must NOT require Dagger: the proof-cost primitives (receipts, parallelism, single-lane pattern) land in `phase_loop_runtime` via GOVLEAN and work on one laptop with zero CI; Dagger/offload is an optional accelerator layered on top, exactly as here.

## Execution policy
- execute: effort=medium, reason=infra wiring with a reference implementation to mirror; fail-closed semantics must be preserved exactly
