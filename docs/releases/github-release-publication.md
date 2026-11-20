# GitHub release records and PyPI publication

PyPI publication uses the existing `publish-pypi.yml` tag workflow and OIDC trusted
publisher. A successful PyPI upload is followed by a separate GitHub Release job.
Only that job receives `contents: write`; the publisher retains its existing
`id-token: write` permission and `pypi` environment. The release job downloads and
verifies the same wheel, sdist and SHA256SUMS artifact without rebuilding.

If only the release-record job fails, rerun failed jobs for that workflow run.
Do not rerun the successful PyPI job or change `skip-existing: false`. An existing
GitHub Release is skipped only when it is published and every expected asset
can be downloaded and matches the verified publication bytes. A draft, missing
asset, download error or byte mismatch fails with recovery instructions. Restore
assets from that run's `phase-loop-runtime-dist` artifact, inspect and publish the
draft if appropriate, then rerun only the failed record job. The job never
overwrites an existing release or repackages its artifacts.

On 2026-11-12 the existing PyPI publications 0.7.27, 0.7.29, 0.7.30 and 0.7.31 were
backfilled as GitHub Release records with registry checksum values and links to
the successful trusted-publishing runs. No artifacts were rebuilt or republished.
Version 0.7.28 was not backfilled: its publication run failed and PyPI has no files
for that version. The existing tag was left untouched.

If the build job's release gate fails on a tag, a fix merged afterwards cannot reach that
tag: a rerun keeps the tag's commit and workflow file, and a dispatch from a branch cannot
publish. Rerunning the failed jobs re-executes the unchanged gate. An attempt that passes it
is valid strict evidence for that attempt, so a bounded number of failed-job reruns is
acceptable while each failure carries the same known host-prerequisite signature and PyPI
still has no files for the version. Any other failure stops the reruns for investigation.
Otherwise leave the tag untouched and release the next version from `main`, as for 0.7.28.

GitHub's latest-release designation alone is not evidence of the newest package
publication or installed version. Reconcile the package registry, tag/workflow
provenance and local installation manifest separately.
