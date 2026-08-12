# Detailed plan: offload agent-harness heavy CI to tailnet host `ai` (r3, board-reconciled)

**Status: held — do not land before agent-harness#477 merges. Lands after the single-lane plan.**
**r3 (2026-08-12): reconciles round-2 board findings (4 seats, all DISAGREE). r2's "mirror the gp
step pair" and "offloaded steps on ubuntu-latest, hosted steps on Blacksmith" were mutually
unimplementable (`runs-on` and `environment:` are job-level; a job-level `if:` cannot read
`secrets`) — all four seats. The topology below replaces prose-by-reference with an explicit job
graph, and the merge-gate is made real (Fable's live check: main currently has NO branch
protection or rulesets — the "fork merges only on green" property is process-only today and MUST
be configured in this change).**

## Task
Move agent-harness's heavy CI execution onto tailnet host `ai` via the `dagger-offload`
composite, with an explicit workflow-job topology that (a) never yields a mergeable state without
a gating suite verdict, (b) never bills Blacksmith for offloaded execution, and (c) never exposes
`TS_AUTHKEY` to forks.

## Job topology (explicit — replaces "mirror gp exactly")
```
elig      runs-on: ubuntu-latest.  Computes eligibility IN A STEP (push-to-main or same-repo PR,
          secret present — secrets are readable in steps, not job-level if) and exports
          outputs.eligible.
offload   runs-on: ubuntu-latest.  needs: elig.  if: needs.elig.outputs.eligible == 'true'.
          Runs the dagger-offload composite (pinned to full SHA) → suite executes on ai.
          FAIL-CLOSED: ai unreachable ⇒ job red. Never a hosted fallback on failure().
hosted    runs-on: blacksmith-4vcpu-ubuntu-2404.  needs: elig.
          if: needs.elig.outputs.eligible != 'true'.  Runs the suite on the hosted runner —
          fork PRs and no-secret events get real CI.
gate      runs-on: ubuntu-latest.  needs: [offload, hosted].  if: always().
          Fails unless exactly one of offload/hosted concluded SUCCESS. This is the ONLY
          required status check for the suite.
```
Why `gate` exists: a conditionally-skipped job reports `skipped`, and **a skipped job satisfies a
required status check** — requiring `offload`/`hosted` directly re-creates the false-green class
one layer up (codex/gemini/Fable convergent). The aggregate check cannot be skipped and cannot
pass without a real suite verdict.

## Merge-gate configuration (new in r3 — in-scope, not assumed)
- Configure branch protection / a ruleset on `main` requiring the `gate` check (plus the
  existing sub-minute checks). **Main currently has neither** — until this lands, "merge only on
  green" is convention, not enforcement. Configuration change is part of this plan's acceptance,
  performed by the maintainer (admin) alongside the workflow landing.

## Host exposure (replaces r2's environment-protection clause — Fable N3)
Environment protection with required reviewers would put a manual approval on EVERY eligible run
(CI stops being automatic) or be toothless without reviewers. Dropped. Actual mechanisms:
GitHub's default first-time-contributor approval for fork workflow runs; `TS_AUTHKEY` withheld
from forks by GitHub secret semantics; tailnet ACL scoping `tag:ci-gp → ai:22` only;
least-privilege rootless `ci-docker`. Residual risk (compromised same-repo write account running
workloads on `ai`) is documented and accepted at maintainer ratification — same posture as the
other offloaded repos.

## Changes
### `.github/workflows/test.yml` (modify)
- restructure per the job topology above; `uses:` pinned to full commit SHA
- python matrix preserved inside the Dagger function (3.10/3.11/3.12 containers)
### `ci/dagger/` (create)
- Dagger module running the exact suite/gate commands, with:
  - **the single-lane plan's selection rule reimplemented per container** (no `matrix.python-version`
    exists inside Dagger): chronology node runs in the 3.10 container only + the Gate A stage —
    without this the offload silently reintroduces 3 × 40-min executions (gemini; Fable N4)
  - **full `.git` object database ingested**, verified by a probe that touches historical blobs
    (`git fsck` or `cat-file --batch-check` over `rev-list --objects`) — a commit-count probe
    passes on blob-filtered clones (Fable fix-3)
  - **junitxml files exported from the `ai` containers back to the workflow** and uploaded as
    artifacts (the single-lane plan's evidence contract must survive offload)
### deferred
- sub-minute workflows stay on Blacksmith; migration cost exceeds their bill

## Documentation impact
- `CHANGELOG.md` — add — CI execution/offload + merge-gate configuration change

## Dependencies & order
1. agent-harness#477 merged (hard gate)
2. single-lane plan landed
3. Dagger module + probes → `elig`/`offload`/`hosted`/`gate` restructure → branch-protection
   configuration → lane-by-lane cutover (pytest matrix, then Gate A)

## Verification
- same-repo PR: `offload` runs on ai (log shows tailnet join + `DOCKER_HOST=ssh://ai`); `hosted`
  skipped; `gate` green; results equal a hosted baseline on the same SHA
- fork-PR simulation: `offload` skipped, `hosted` RUNS and its result drives `gate`
- eligible + `ai` unreachable ⇒ `offload` red ⇒ `gate` red (fail-closed observed)
- suite-skip simulation (both offload and hosted forced-skip on a scratch branch) ⇒ `gate` red —
  the skipped-satisfies-required-check hole is proven closed
- `.git` blob probe green inside the container; junitxml artifacts present
- billing: representative push bills Blacksmith only for `hosted` (fork-path) and sub-minute jobs

## Acceptance criteria
- [ ] No mergeable state without a gating suite verdict: `gate` is a required check on `main`
      (ruleset/protection configured and observed), and the forced-skip simulation turns `gate` red
- [ ] Eligible path fail-closed on unreachable `ai`; forks never receive `TS_AUTHKEY`
- [ ] Chronology node runs in exactly the 3.10 container + Gate A stage under Dagger; junitxml
      artifacts exported and uploaded
- [ ] Billed Blacksmith minutes for a representative eligible push ≤ the sub-minute jobs
- [ ] `uses:` pinned to full SHA

## Generalizability note (unchanged)
Fleet-internal. Client-facing proof-cost primitives land in `phase_loop_runtime` via GOVLEAN and
require no Dagger/CI/network (EC-GOVLEAN-4); this plan is an optional accelerator layered on top.

## Execution policy
- execute: effort=medium, reason=public-repo merge-gate semantics + job-graph restructure; the
  false-green class has now survived two review rounds in different shapes — prove it dead by
  the forced-skip simulation, not by reading the YAML
