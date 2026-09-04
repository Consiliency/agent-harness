# The publish-pypi build timeout is 25 minutes, and the number is measured

`publish-pypi.yml`'s `build + verify wheel + sdist` job runs with
`timeout-minutes: 25`. Over the 18 completed runs sampled on 2026-09-04 it
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

Raise a timeout only against a measurement, and record the measurement here.
