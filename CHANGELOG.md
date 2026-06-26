# Changelog

All notable changes to `agent-harness` (the `phase-loop-runtime` package + the
`phase-loop-skills` bundle) are documented here. This project adheres to semantic
versioning; the release tag, the package `version`, and this file are kept in lockstep.

## v0.1.3

- **Fix:** break the cross-phase dirty start-gate dead-end (#1) — the start-gate's
  recommended `reconcile` recovery no longer points at a command that only accepts
  `blocked` phases, so a repo with accumulated `.phase-loop/` state can always recover.
- **Hygiene:** removed a committed `build/` directory + `egg-info` (a stale build
  artifact carrying `__version__ = "0.1.0"` that setuptools intermittently reused,
  making installs report the wrong version) and added a `.gitignore` for build artifacts.

## v0.1.2

Packaging and documentation polish — no runtime behavior change.

- `phase-loop-runtime` package `version` now tracks the release tag (was reporting
  `0.1.0` on the `v0.1.1` tag).
- Public package metadata: harness-neutral `description` (no longer "vendored for
  dotfiles"), `[project.urls]`, license classifier, Python-version classifiers, author.
- Rewrote `phase-loop-runtime/README.md` for the public install flow (the prior copy
  referenced private `vendor/...` paths and "not published").
- Added this CHANGELOG, a `phase-loop-skills/` bundle README, and a
  `docs/TEAM-ONBOARDING.md` quickstart.
- Installer default ref bumped to `v0.1.2`.

## v0.1.1

- Synced the runtime to the post-TESTDECOUPLE state: bundled `_contract_docs/` and
  `_test_fixtures/` package data so the runtime-core test suite resolves them via
  `importlib.resources` and passes standalone in the extracted layout.
- Re-ran the public-release scrub.

Supersedes v0.1.0 (which predated TESTDECOUPLE and was missing the bundled
contract-docs package data).

## v0.1.0

- Initial public extraction of the harness-neutral phase-loop runtime + the
  cross-harness workflow-skills bundle from a private fleet repo, under Apache-2.0.
- **Superseded by v0.1.1** — do not pin v0.1.0.
