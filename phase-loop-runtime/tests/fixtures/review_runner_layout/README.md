Templates for the synthetic OCI layouts that `tests/test_review_runner_recipe.py` generates
on disk (RRIMAGE contract §3.4, §4).

The test fills every `computed-in-test` value, writes each blob under `blobs/sha256/<hex>`
with its digest computed from the written bytes, and builds the top-level `index.json`.
No value here comes from a real build, image or registry.
