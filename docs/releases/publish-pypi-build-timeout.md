# The publish-pypi build timeout is per path, and each number is measured

`publish-pypi.yml`'s `build + verify wheel + sdist` job runs with
`timeout-minutes: 55` on a pull request and `140` on a tag push or a manual
dispatch. The pull-request bound was 25 until agent-harness#1993; see
"The pull-request bound must outlast the gate's own bounds" below. The two paths run different work (see below). On pull requests, over
the 18 completed runs sampled on 2026-09-04 the job
averaged **7.7 minutes** and peaked at **12**, so 25 is roughly twice the worst
observed run — enough for a slow runner or a cold cache, and still a fast failure
if the job wedges.

It was previously **100**, about 8x the worst case, which meant a hang cost an
hour and a half before anything reported.

## Why a tight bound here is worth having

This job has already gone bimodal once. Until 2026-09-03, 21 of 25 runs took
6–12 minutes and three took **62–66**, with Gate A accounting for the entire job
in both cases (66 of 66 minutes when slow, 11 of 11 when normal). The cause was
the heavy CONFORM chronology node running on pull requests.

Two changes that day fixed it: *run the CONFORM chronology node only where its
verdict can change*, and agent-harness#753 *pull requests defer the chronology node*. The
60-minute runs were branches that had not picked them up yet — the same branch
went from 62 minutes to 7 with no change to its own content.

At 100 minutes a recurrence would burn 90 minutes before failing. At 25 it fails
in under half that.

## What was deliberately left alone

- `test.yml` `suite (offloaded to ai)` keeps **120**. It genuinely runs long when
  the chronology node is retained, and its own comment records **7:45** when the
  node is deselected. 120 is the right headroom for the retained case.
- `test.yml` `pytest` and `clean-room` were left at **100**: at the time both were
  skipped on pull requests, so the sampled runs carried no timing for them, and any
  tighter number would have been a guess. Since then `pytest` runs on pull requests
  (currently its py3.12 lane), because the offload path is disabled in `test.yml`
  (`OFFLOAD_SANDBOX_READY: 'false'`), and
  `clean-room` runs only on push, schedule, dispatch and tags (agent-harness#1029) with
  a stopgap of **150** (agent-harness#1297).

## The tag and dispatch path runs the full suite, and it is measured too

Gate A deselects the chronology node **only** on `pull_request` runs
(`GATE_A_DESELECT_CHRONOLOGY`). A tag push or a `workflow_dispatch` runs the
full standalone suite from the exact wheel, which is the point of the release
gate. The 2026-09-04 sample contained no tag run, so the 25-minute bound was set
against pull-request timings only, and the first tag after it hit the cap:

- `v0.7.14` (before the change): trusted-publish workflow `32783112944`, build job
  `97609245453`, **70 min 18 s**, success.
- `v0.7.15` (2026-09-21): workflow `35563072987`, build job `106219492015`,
  **cancelled at 25 min 15 s** by the timeout, at 50% of the Gate A suite; the
  publish job was skipped and nothing reached PyPI.

The tag/dispatch bound is `140`: twice the one measured run, which is the
headroom agent-harness#757 applied on the pull-request path (25 is about twice its 12-minute
maximum). It is expressed as
`${{ github.event_name == 'pull_request' && 25 || 140 }}` — an Actions
value-select, safe because the pull-request operand is non-zero — so the
pull-request bound stays where the measurement put it. Tighten the tag bound only
against a sample of tag runs, and record the sample here.

**A tag cut before this change cannot be rescued by it.** A tag run executes the
workflow file at the tagged commit, and a `workflow_dispatch` from a branch makes
the publish job's `startsWith(github.ref, 'refs/tags/v')` condition false. The
existing tag-triggered workflow path to PyPI for such a version is to re-point the tag at a head that carries
this file (maintainer-gated); the version number is unchanged when nothing was
published, and the release record is completed against the run that publishes.

Raise a timeout only against a measurement, and record the measurement here.

## The pull-request bound must outlast the gate's own bounds

agent-harness#1993 moved the agy release gate's host preparation into
`ci/seat-caps-host.sh` and added two always-run steps after the gate: the scratch
teardown and the evidence upload. A job killed by its own timeout runs neither, so the
job bound must exceed the gate step's bound plus theirs. Every command in the gate has
its own `timeout`, and their worst-case sum plus three minutes for installing `uv` and
syncing the locked environment fits in the gate step's `timeout-minutes: 40` (the
verifier's own wrapper is 1200 s; its inner suite run is bounded at 900 s, against a
measured 104-141 s). With five minutes for checkout, Python and the sandbox prerequisites,
3 for teardown and 5 for the upload, the pull-request job needs 53 minutes and is set to
55. `test_every_gate_bound_fits_inside_the_job_so_cleanup_and_evidence_still_run` keeps
these numbers consistent. Measured pull-request runs are unchanged by this: the bound only
decides when a wedged gate is reported, now with its evidence. The tag and dispatch bound
stays 140, which already covers the same steps plus the full Gate A suite.
