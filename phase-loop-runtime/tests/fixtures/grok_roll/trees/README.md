# grok release-catalog tree fixtures

`signed_entry.json` is a release entry carrying the one real registry signature vector of
GROKROLL §0 (`@xai-official/grok-linux-x64@1.0.89`): its `version`, `package` and
`tarball_integrity` are what the signature binds. Its `binary_sha256` and `binary_bytes`
are fixture values; the stored signature does not bind them (GROKROLL §1).

`tests/test_grok_release_catalog.py` builds each `check_tree` fixture tree from this entry
and the shipped package data in a temporary directory, changing one file per case.
