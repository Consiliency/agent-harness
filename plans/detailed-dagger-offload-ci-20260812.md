# Detailed plan: offload agent-harness heavy CI to tailnet host `ai` via dagger-offload (r2, panel-reconciled)

**Status: held — do not land before agent-harness#477 merges. Land after the single-lane plan.**
**r2 (2026-08-12): reconciled against board findings (codex red-team + grok adversarial, both DISAGREE on r1). r1's default eligibility design was WRONG and is replaced wholesale — see Eligibility contract.**

## Task
Move agent-harness's heavy CI execution onto tailnet host `ai` via the proven
`Consiliency/ci-actions/dagger-offload` composite, without weakening the merge gate for a PUBLIC
repo and without leaving the billing clock running on a paid runner.

## Eligibility contract (replaces r1's — r1 was unsafe)
Exhaustive, mutually exclusive branches, mirroring `governed-pipeline/.github/workflows/test.yml`
exactly (its offloaded/hosted step pair at :104–:152):

1. **eligible = true** (push to main, or same-repo PR, with `TS_AUTHKEY` present): the offloaded
   step runs and is **fail-closed** — `ai` unreachable ⇒ job red. Never a fallback on `failure()`.
2. **eligible = false** (fork PR, or secret absent): the **hosted suite step runs** (`if:
   eligible != 'true'`), so untrusted contributions still get real CI on hosted runners and can
   merge on genuine green. Forks never receive `TS_AUTHKEY` (GitHub secret withholding + the
   trust gate).
3. There is **no path where the job succeeds without executing the suite.** r1's "no-secret →
   red, no hosted fallback" acceptance criterion is deleted: it contradicted the reference
   pattern and, combined with the composite's ineligible no-op-success behavior, permitted a
   false-green merge gate on fork events.

## Billing contract (new in r2 — codex finding)
A synchronous `dagger call` does NOT stop the calling runner's clock. Offloaded jobs therefore
must not orchestrate from a billed Blacksmith runner. Orchestration moves to `runs-on:
ubuntu-latest` (free for public repos) for the offloaded branches; the hosted fallback branch may
stay on Blacksmith. Acceptance measures billed Blacksmith minutes, not wall time.

## Changes
### `.github/workflows/test.yml` (modify)
- add the `elig` trust-gate step (gp pattern) and the offloaded/hosted step pairs per the
  eligibility contract; `uses:` pinned to a full commit SHA (gp does; r1 under-specified)
- offloaded branches: `runs-on: ubuntu-latest`; hosted branches unchanged
- python-version matrix preserved in the Dagger function (3.10/3.11/3.12 containers)
### `ci/dagger/` (create)
- Dagger module running the exact suite/gate commands. MUST ingest the full git object database
  (the chronology node runs `git cat-file`/`rev-list`/historical diffs; the reference module
  needed explicit `.git` grafting for exactly this — codex finding). Verify with a probe that
  `git rev-list --count HEAD` inside the container equals the host value.
### Host hardening note (codex threat model)
- `ai` exposure on the offload path = a compromised same-repo write account editing workflow/
  module code to run arbitrary workloads via rootless Docker as `ci-docker`. Mitigation in this
  plan: GitHub **environment protection** on the offload environment (maintainer approval for
  first-time/modified-workflow runs), least-privilege `ci-docker`, and the existing ACL scoping
  `tag:ci-gp → ai:22` only. Residual risk documented, accepted by maintainer at ratification.
### deferred
- sub-minute workflows (docs-audit, scrub, release-consistency, skills-parity) stay on
  Blacksmith; migration cost exceeds their bill.

## Documentation impact
- `CHANGELOG.md` — add — CI execution/offload change

## Dependencies & order
1. agent-harness#477 merged (hard gate)
2. single-lane plan landed
3. Dagger module + `.git` ingestion probe → offloaded pytest matrix → offloaded Gate A

## Verification
- same-repo PR: offloaded steps run on `ai` (log shows tailnet join + `DOCKER_HOST=ssh://ai`);
  results equal a hosted baseline on the same SHA
- **fork-PR simulation: hosted suite step RUNS and its result gates the job** (r1 tested only key
  withholding — insufficient; codex finding)
- eligible + `ai` unreachable ⇒ job red (fail-closed proof)
- `.git` probe: container `git rev-list --count HEAD` == host value
- billing: representative push shows Blacksmith minutes only for hosted-branch/sub-minute jobs

## Acceptance criteria
- [ ] No job path succeeds without executing the suite (fork, no-secret, and eligible paths all
      proven by observed runs)
- [ ] Eligible path fail-closed on unreachable `ai`; forks never receive `TS_AUTHKEY`
- [ ] Chronology node passes inside the Dagger container (git history fully present)
- [ ] Billed Blacksmith minutes for a representative push ≤ the sub-minute jobs
- [ ] `uses:` pinned to full SHA; offload environment protected

## Generalizability note (unchanged)
Fleet-internal. Client-facing proof-cost primitives land in `phase_loop_runtime` via GOVLEAN and
require no Dagger/CI/network (EC-GOVLEAN-4); this plan is an optional accelerator layered on top.

## Execution policy
- execute: effort=medium, reason=public-repo merge-gate semantics; the r1 defect class lives here
