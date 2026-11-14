# Changelog fragments

Don't edit `CHANGELOG.md` `[Unreleased]` in a pull request. Add one file here instead:

```text
changelog.d/<number>.<type>.md
```

- `<number>` is the agent-harness issue or pull request the entry is about
  (`1702.ci.md` for agent-harness#1702). For a second entry on the same number, use
  `<number>.<type>.2.md`.
- `<type>` is one of `breaking`, `feature`, `fix`, `change`, `docs`, `ci`. The release
  orders entries by type, then number.
- The file is the entry exactly as it should read in the CHANGELOG: a `### ` heading
  line, then the body. Don't use `#` or `##` headings. Qualify every issue and pull
  request number (`agent-harness#123`).

Each pull request adds its own file, so pull requests no longer conflict with each other
over `CHANGELOG.md`. The docs-freshness audit accepts a fragment wherever it asks for a
CHANGELOG entry.

At the release cut, `python scripts/assemble_changelog.py --version X.Y.Z` moves every
fragment into `CHANGELOG.md` under a new `## [X.Y.Z] - <date>` heading and deletes the
fragments. `--dry-run` prints the result without changing anything, and `--check` only
validates the fragments.
