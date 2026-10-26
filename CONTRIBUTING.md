# Contributing to agent-harness

Agent-facing conventions are in [`AGENTS.md`](AGENTS.md). Read it first; the rules
below don't repeat it.

## Layout

- `phase-loop-runtime/`: the `phase-loop-runtime` package (engine, CLI, tests).
- `skills-src/`: the authored workflow skills, one tree per harness. Edit skills here.
- `phase-loop-skills/` and `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/`
  are **generated** from `skills-src/`. Never hand-edit them; regenerate them (see
  [`docs/phase-loop/skills-canonical-source.md`](docs/phase-loop/skills-canonical-source.md)):

  ```sh
  python phase-loop-runtime/scripts/regenerate_skills_bundle.py
  python phase-loop-runtime/scripts/sync_skills_bundle.py
  ```

- `consiliency-harness/`: the `consiliency-harness` dependency shim.
- `docs/`: guides, contracts, release records and registers.

## Local checks

Requirements: Python 3.12 or newer for the runtime (`requires-python = ">=3.12"`), plus
[`uv`](https://docs.astral.sh/uv/).

- `make check` runs the checks your change can affect against `origin/main`. That covers
  ruff with CI's pinned version and config, plus the tests your diff can reach. They run
  in a clean environment with a throwaway HOME and only the system PATH, which is how
  CI-only failures reproduce locally. `make check-full` runs the whole standalone suite.
  See `phase-loop-runtime/scripts/local_check.py --help` (and `--dry-run` to see what
  it would run).
- To run specific tests the way CI does, from the repository root:

  ```sh
  uv sync --project phase-loop-runtime --group test --extra visual --locked
  PYTHONPATH="$PWD/phase-loop-runtime/src:$PWD/phase-loop-runtime/tests" \
    phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_entry_doc_check.py
  ```

  Use an absolute `PYTHONPATH`. A test that starts a child Python from another directory
  would otherwise import an installed copy instead of the tree under test.
- Docs checks, as CI runs them:

  ```sh
  python -m phase_loop_runtime.entry_doc_check --repo .
  python -m phase_loop_runtime.cli docs-audit --repo . --base origin/main --json
  ```

## Pull requests

- Branch from `main` and open a pull request against `main`. Force-pushes to `main` are
  blocked.
- These checks must pass before a merge (branch protection on `main`):

  | Check | Workflow |
  |---|---|
  | `suite gate` | `test.yml` (the aggregate of the test suite jobs) |
  | `lint (pyflakes)` | `test.yml` |
  | `chronology retention guard` | `test.yml` |
  | `docs-freshness audit` | `docs-audit.yml` |
  | `gitleaks` | `scrub.yml` |
  | `check` | `release-consistency.yml` (package version consistency) |

  These also run on pull requests and are worth keeping green, but are not required:
  `entry-point docs verification` (`entry-doc-check.yml`), `skills-parity.yml`,
  `roadmap ownership (advisory)`, the package build workflows and
  `qualified-agy-image.yml`.
- **The Gate A suite (run against a clean-room install of the wheel) does not run on pull requests.**
  It runs on pushes to `main`, nightly and on dispatch (`test.yml`), and in the release
  build on tags (`publish-pypi.yml`). If your change touches
  packaging, `skills-src/`, `docs/` paths that tests read, or workflows, dispatch it on
  your branch before merging:

  ```sh
  gh workflow run test.yml --ref <your-branch> -f chronology=false
  ```

- `docs-freshness audit` fails when a release-facing surface changes without a doc change
  or a recorded decision in `.doc-decisions.json`. Update the docs in the same pull request.
- Changing skill text in `skills-src/` can change the recorded launch-spec golden
  (`phase-loop-runtime/tests/data/launchspec_golden/`). Regenerate the bundles and update
  the golden in the same pull request.
- Add a CHANGELOG entry under `[Unreleased]` for user-visible behaviour.
- Reference issues and pull requests as `agent-harness#123`, never as a bare `#123`
  (see [`AGENTS.md`](AGENTS.md)).
- Larger changes are reviewed by a cross-vendor advisor board
  (`phase-loop advisor-board`, see
  [`docs/advisor-board-capabilities-card.md`](docs/advisor-board-capabilities-card.md)).
  How to keep that review loop bounded is in
  [`docs/agent-phase-convergence.md`](docs/agent-phase-convergence.md#8-bound-the-review-loop-portable).

## Security

This repository is public. Don't describe a security weakness in an issue, pull request,
commit message or test name. Report it privately with the **Report a vulnerability**
button on the repository's **Security** tab (Security → Advisories). See
[`SECURITY.md`](SECURITY.md).

## License

Contributions are made under the [Apache-2.0](LICENSE) license.
