# Detailed plan: diff-independent entry-point documentation verification

**Revision 2** — rewritten after a cross-vendor panel returned **DISAGREE ×2**. Every finding
below was verified against the tree before being folded in; two of them made the first
revision unbuildable as written. The changes are substantial enough that this revision
requires re-review before implementation.

## Task

Implement the check described in agent-harness#568: verify entry-point documentation against
properties that do **not** depend on a git diff, and wire it into CI.

`docs_audit` is change-coupled by contract — it classifies *changed paths* and enforces that a
changed public surface has a doc decision. It answers "did the docs change when the code
changed?" and structurally cannot answer "are the docs still true?". The seven defects found
by hand on 2026-08-16 all arose with **no diff touching the doc**: a `v0.1.5` install pin
rotted through six releases untouched; skill inventories went stale because skills were added
*elsewhere*.

## What the panel changed, and why

**1. Arm 2 was self-contradicting — the fatal finding.** Revision 1 said a pin passes if it
"matches a real git tag". **`v0.1.5` is a real tag** (verified: `git tag --list | grep -c
'^v0.1.5$'` → 1). So the rule would have *passed* the exact historical defect that revision 1's
strongest acceptance criterion demanded it *catch*. The plan contradicted itself.

The rule is not "does this ref exist" but **"is this pin stale for the package it names"**.
Redesigned below.

**2. The positive control would have failed on day one.** Of 17 slash-containing backtick
tokens in the root README, at least five are deliberately not repo paths: `~/.claude/skills`
(home), `Consiliency/agent-harness#130` (this repo's own issue-citation convention),
`specs/phase-plans-v<N>.md` (metavariable), `share/phase-loop-runtime/...` (install path),
`.consiliency/manifest` (runtime-created). Revision 1 asserted skip classes were unnecessary;
they are load-bearing.

**3. Arm 4 was theatre.** It could not execute the quickstart (network + `phase-loop run`
pushes by default), so it degraded to "commands are allowlisted or have a note nearby".
**Dropped.** Its slot goes to a check that is fully decidable and covers a real observed
defect: published-README rendering context.

**4. Revision 1's research summary contained a false claim.** It stated
`GENERAL_PUBLIC_GLOBS` contains both `README.md` and `**/README.md`. Verified: it contains
only root `README.md`; only `DOC_SURFACE_GLOBS` has both.

**5. `check_version_pins(text, path)` lacked the context to resolve anything.** There is **no
root `pyproject.toml`**, and the monorepo has two independently versioned packages
(`phase-loop-runtime` 0.7.13, `consiliency-harness` 0.6.1). The signature must take repo and
package context.

**6. `**/README.md (package roots only)` is not an expressible surface.** Globs cannot say
"package roots". The tree contains dozens of generated override READMEs under
`skills_bundle/**`; if the walk leaks into them the positive control dies. Replaced with an
explicit allowlist.

**7. Scope exceeded one bounded change.** Split into A and B on the annotation seam.

## Scope: this plan is A only

**Plan A (this document):** taxonomy addition, arm 1 (paths), arm 2 (pin freshness), arm 3
(published-README rendering), suppression mechanism, workflow, CHANGELOG.
**Plan B (separate, later):** annotated inventories. It needs a marker grammar in live docs
and is the only arm requiring new markup — it should not gate the arms that caught real
defects.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/entry_doc_check.py` (create)

Module shape mirrors `roadmap_lint.py`: importable API + `main(argv) -> int` + `python3 -m`
entry (`roadmap_lint.py:394`, `:748`, `:798`). **No `phase-loop` subcommand** — `cli.py` is
owned by the in-flight FABPUB phase (registration shape is at `cli.py:388`, not modified).

- `ENTRY_DOCS` — add — an **explicit tuple**, not globs: `README.md`, `AGENTS.md`,
  `CLAUDE.md`, `phase-loop-runtime/README.md`, `phase-loop-skills/README.md`,
  `consiliency-harness/README.md`. A new package README is added here deliberately; silence
  is preferable to a walk that swallows generated stubs.
- `PLACEHOLDERS` — add — closed grammar, position-sensitive: `<TAG>` valid **only** in a ref
  position, `<VERSION>` **only** in a package-version position. `<PATH>`/`<HARNESS>` are
  path/CLI metavariables and are **not** accepted in pin positions (panel finding).
- `Finding(file, line, arm, message, code)` — add — `code` is the machine-readable reason a
  suppression must cite.
- `check_paths(text, doc_path, repo)` — add — **arm 1**. Backtick tokens that look like repo
  paths must resolve, trying **repo-root first, then the document's own directory**. Skip
  classes, each a named `code`: `~`-prefixed (home), `owner/repo#N` (issue citation), any
  token containing `<...>` (metavariable), URL schemes, `*` globs, and fenced code blocks.
- `check_pin_freshness(text, doc_path, repo)` — add — **arm 2, redesigned**. A pin is a
  *claim about a package's current version*, so it is checked for **staleness**, not
  existence:
  - `pip install <dist>==<V>` → `<V>` must equal that distribution's own
    `pyproject.toml` version. `phase-loop-runtime==0.7.13` passes today; the next bump fails
    CI until the README moves.
  - `@v<X.Y.Z>` in a git-install URL → must equal the repository's **latest** release tag
    (`git tag --list --sort=-v:refname | head -1`), or be `<TAG>`.
  - **This makes the historical `v0.1.5` a finding even though the tag exists** — which is the
    behaviour the acceptance criterion always demanded and revision 1 could not deliver.
  - Requires repo + package context, hence the signature change.
- `check_published_rendering(text, doc_path, repo)` — add — **arm 3 (replaces old arm 4)**.
  For a README that ships as a package long-description (`phase-loop-runtime/README.md`,
  `consiliency-harness/README.md`), a non-fragment relative link is a defect: GitHub rewrites
  relative links using repository context, PyPI does not. This catches the observed
  `../phase-loop-skills` defect **deterministically and offline**. Parse links with a closed
  grammar — do **not** reuse arm 1's backtick heuristic.
- `SUPPRESSIONS` / `load_suppressions(repo)` — add — a checked-in file mapping
  `file:line:code` → reason string. Every entry needs a non-empty reason; the check prints the
  active count and **fails if it exceeds a budget constant**. This gives the positive control
  a remedy that is not "disable the check", without letting suppression become the default.
- `check_repo(repo)` / `main(argv)` — add — `0` clean, `1` findings, `2` usage/IO error.

### `phase-loop-runtime/src/phase_loop_runtime/docs_surfaces.py` (modify)

- `DOC_SURFACE_GLOBS` — modify — add `"AGENTS.md"` and `"CLAUDE.md"` (verified: zero
  occurrences today). Mechanical prerequisite, not the deliverable.

### `phase-loop-runtime/tests/test_entry_doc_check.py` + `tests/fixtures/entry_docs/` (create)

**Fixtures must be constructed repos, not loose `.md` files** — arms 2 and 3 need a git repo,
tags, and package metadata. Build with `TemporaryDirectory()` per `test_docs_audit.py:84`,
each containing a `pyproject.toml` and an initialised git repo with a tag.

- `test_current_repo_is_clean` — the **positive control**; must pass against live docs.
- Per-arm negatives, asserting the `arm` **and** `code`, not merely non-empty output.
- **Adversarial positives** — the panel's key addition. Each arm gets fixtures that are
  *correct but tricky*: a `~/` path, an `owner/repo#N` citation, a `<N>` metavariable, a
  fenced-block path, a fragment-only link, `<TAG>` in a ref position, `<VERSION>` in a version
  position. These must produce **zero** findings.
- `test_v015_historical_pin_is_stale` — the mutation-coupling arm: the pin at commit
  `8f191d99` must be reported, *with* the reason being staleness rather than nonexistence.
- `test_suppression_requires_reason_and_respects_budget`.

### `.github/workflows/entry-doc-check.yml` (create)

Mirrors `docs-audit.yml` structurally. **`fetch-depth: 0`, not `fetch-tags: true`** — the
latter at default depth is a known `actions/checkout` footgun (actions/checkout#1781) and arm
2 needs tags. Triggers: `pull_request`, `push: branches [main]`, **and `push: tags ['v*']`** —
a tag push changes arm 2's input, so the check must re-run when it does.

## Documentation impact

- `CHANGELOG.md` — add — a new CI check is a public surface; the docs-audit gate requires it.
- `docs/agent-phase-convergence.md` — modify — its pin section warns that a naive 40-hex scan
  needs an allowlist; name this check as the worked implementation. **Deferred to the
  implementing PR**, not done here.
- `README.md`/`AGENTS.md`/`CLAUDE.md` — no change. The check verifies them.

## Dependencies & order

1. `docs_surfaces.py` taxonomy addition (independent, mechanical).
2. Suppression mechanism **before** any arm — otherwise the first arm to fire has no remedy.
3. Arm 1 (paths) with its skip classes and adversarial positives.
4. Arm 2 (pin freshness) — needs package-context plumbing.
5. Arm 3 (published rendering).
6. Workflow last, once `main()` exit codes are stable.

No FABPUB or PROOFGATE surface is touched; this can run concurrently.

## Verification

```sh
cd phase-loop-runtime
PYTHONPATH=src:tests python3 -m pytest tests/test_entry_doc_check.py -q

# The positive control against LIVE docs — must exit 0, or the check is unusable.
PYTHONPATH=src python3 -m phase_loop_runtime.entry_doc_check --repo ..; echo "exit=$?"

# Mutation coupling: the historical stale pin must be a finding, for the right reason.
git show 8f191d99:phase-loop-runtime/README.md > /tmp/old.md
PYTHONPATH=src python3 -m phase_loop_runtime.entry_doc_check --file /tmp/old.md --repo ..
# expect exit 1 with code=stale_pin (NOT unknown_ref)

# Adversarial positives must be silent.
PYTHONPATH=src python3 -m pytest tests/test_entry_doc_check.py -q -k adversarial

PYTHONPATH=src:tests python3 -m pytest tests/test_docs_audit.py -q   # taxonomy regression
```

## Acceptance criteria

- [ ] `entry_doc_check --repo .` exits **0** against current live entry docs, asserted by
      `test_current_repo_is_clean`, with the suppression file **empty or within budget** — a
      positive control bought by blanket suppression is not a positive control.
- [ ] The historical `@v0.1.5` pin at `8f191d99` is reported with code `stale_pin`. The tag
      exists; the finding must rest on staleness against `phase-loop-runtime`'s current
      version, not on the ref being unresolvable.
- [ ] Every arm has both a negative fixture (reported, asserted by `arm` and `code`) and an
      adversarial-positive fixture (correct-but-tricky, **zero** findings).
- [ ] A relative non-fragment link in a package README is reported; the same link in the root
      README is not.
- [ ] `AGENTS.md`/`CLAUDE.md` are in `DOC_SURFACE_GLOBS` and `test_docs_audit.py` passes
      unchanged.

## Execution Policy

- execute: effort=medium, reason=three parsing arms with false-positive risk; the markdown
  edge cases (fenced blocks, metavariables, issue citations, fragment links) are where this
  breaks, not the logic.

## Scope honesty

Arm 3 checks a *rendering-context* property, not link liveness — it never fetches a URL. It
does not cover agent-harness#567 (the raw traceback from `phase-loop run` in a fresh repo),
which stays a separate runtime fix. Do not attach a defect count to this check: **count the
arms, not the incident list**. Annotated inventories are plan B and are not claimed here.
