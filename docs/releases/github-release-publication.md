# GitHub release records and PyPI publication

PyPI publication uses the existing `publish-pypi.yml` tag workflow and OIDC trusted
publisher. A successful PyPI upload is followed by a separate GitHub Release job.
Only that job receives `contents: write`; the publisher retains its existing
`id-token: write` permission and `pypi` environment. The release job downloads and
verifies the same wheel, sdist and SHA256SUMS artifact without rebuilding.

If only the release-record job fails, rerun failed jobs for that workflow run.
Do not rerun the successful PyPI job or change `skip-existing: false`. An existing
GitHub Release is preserved, including its notes and assets. Inspect its contents
before treating a manually created record as equivalent to the workflow output.

On 2026-11-12 the existing PyPI publications 0.7.27, 0.7.29, 0.7.30 and 0.7.31 were
backfilled as GitHub Release records with registry checksum values and links to
the successful trusted-publishing runs. No artifacts were rebuilt or republished.
Version 0.7.28 was not backfilled: its publication run failed and PyPI has no files
for that version. The existing tag was left untouched.

GitHub's latest-release designation alone is not evidence of the newest package
publication or installed version. Reconcile the package registry, tag/workflow
provenance and local installation manifest separately.
