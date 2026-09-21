# The publish-pypi build timeout is per path, and each number is measured

`publish-pypi.yml`'s `build + verify wheel + sdist` job runs with
`timeout-minutes: 25` on a pull request and `140` on a tag push or a manual
dispatch. The two paths run different work (see below). On pull requests, over
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
verdict can change*, and #753 *pull requests defer the chronology node*. The
60-minute runs were branches that had not picked them up yet — the same branch
went from 62 minutes to 7 with no change to its own content.

At 100 minutes a recurrence would burn 90 minutes before failing. At 25 it fails
in under half that.

## What was deliberately left alone

- `test.yml` `suite (offloaded to ai)` keeps **120**. It genuinely runs long when
  the chronology node is retained, and its own comment records **7:45** when the
  node is deselected. 120 is the right headroom for the retained case.
- `test.yml` `pytest` and `clean-room` keep **100**. Both are skipped on pull
  requests, so the sampled runs carry no timing for them; any tighter number
  would be a guess rather than a measurement.

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
headroom #757 applied on the pull-request path (25 is about twice its 12-minute
maximum). It is expressed as
`${{ github.event_name == 'pull_request' && 25 || 140 }}` — an Actions
value-select, safe because the pull-request operand is non-zero — so the
pull-request bound stays where the measurement put it. Tighten the tag bound only
against a sample of tag runs, and record the sample here.

**A tag cut before this change cannot be rescued by it.** A tag run executes the
workflow file at the tagged commit, and a `workflow_dispatch` from a branch makes
the publish job's `startsWith(github.ref, 'refs/tags/v')` condition false. The
only path to PyPI for such a version is to re-point the tag at a head that carries
this file (maintainer-gated); the version number is unchanged when nothing was
published, and the release record is completed against the run that publishes.

Raise a timeout only against a measurement, and record the measurement here.
