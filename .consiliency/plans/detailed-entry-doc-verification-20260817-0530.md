# Detailed plan: diff-independent entry-point documentation verification

## Task

Implement the check described in agent-harness#568: verify entry-point documentation
(`README.md` at every package root, `AGENTS.md`, `CLAUDE.md`) against properties that do
**not** depend on a git diff, and wire it into CI.

The motivating defect class: `docs_audit` is change-coupled by design — it classifies
*changed paths* and enforces that a changed public surface has a satisfying doc decision. It
answers "did the docs change when the code changed?" and structurally cannot answer "are the
docs still true?". A 2026-08-16 sweep found seven defects, none visible to any gate, because
**every one arose with no diff touching the doc** (a `v0.1.5` install pin rotted through six
releases untouched; skill lists went stale because skills were added *elsewhere*).

Constraints carried from the review panel and from the phase in flight:
- Must not touch `phase-loop-runtime/src/phase_loop_runtime/cli.py` — the FABPUB phase owns
  it (its plan explicitly claims `cli.py` for the coordinator-root change).
- Must not touch `panel_invoker.py`.
- Falsifier needs a **positive control**; negatives live in **fixtures**, never by mutating
  live docs.
- The placeholder token must be **closed** (defined exactly), or the pin arm is
  unimplementable.
- The claim must be scoped to what the arms actually cover — do not assert a defect count.

## Research summary

Grounded in this session against the live tree (not inferred):

- **Module pattern to mirror:** `phase_loop_runtime/roadmap_lint.py` — `lint_roadmap_text(text) -> List[str]`
  (`:394`), `main(argv) -> int` (`:748`), `sys.exit(main(sys.argv))` (`:798`). Importable API
  plus `python3 -m` entry, integer exit code, issues printed to stderr.
- **CLI registration** is a name in the subcommand tuple at `cli.py:388` with a dispatch
  branch near `:482`. **This plan does not add a subcommand** precisely because `cli.py` is
  owned by FABPUB; the check ships as a `python3 -m` module and a CI step. A `phase-loop`
  subcommand can be added later by whoever owns `cli.py` next.
- **CI pattern to mirror:** `.github/workflows/docs-audit.yml` — its own workflow, single job,
  `runs-on: blacksmith-4vcpu-ubuntu-2404`, `timeout-minutes: 10`, checkout → setup-python 3.12
  → `pip install ./phase-loop-runtime` → run the module. Triggers on `pull_request` and
  `push: branches [main]`.
- **Fixture convention:** `tests/test_docs_audit.py` builds throwaway trees with
  `TemporaryDirectory()` (`:17`, `:84`, `:147`…). `tests/fixtures/<name>/` holds static
  fixture data. `tests/phase_loop_test_utils.py` holds shared helpers.
- **Taxonomy gap confirmed:** `docs_surfaces.py` has `README.md` and `**/README.md` in both
  `GENERAL_PUBLIC_GLOBS` and `DOC_SURFACE_GLOBS`, and **zero** occurrences of `AGENTS.md` or
  `CLAUDE.md`.
- **No existing link/path checker** was found in `tests/` or `.github/` — this does not
  duplicate anything.

**Arm 4 required a design change, recorded here rather than discovered in implementation.**
"Quickstart commands are executable as written" cannot mean *execute them*: the root
quickstart contains `pip install` (network + installs), `git clone` (network), and
`phase-loop run` — which **commits and pushes by default**. Executing that block in CI would
be harmful. Arm 4 is therefore redefined as a *documentation contract* check (see below), and
the claim narrows accordingly. This is a reduction from #568's wording and is called out as
such.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/entry_doc_check.py` (create)

New module, mirroring `roadmap_lint.py`'s shape. No existing module has a home for this:
`docs_audit` is diff-coupled by contract and must not grow a diff-independent mode.

- `ENTRY_DOC_GLOBS` — add — the surface: `README.md`, `**/README.md` (package roots only,
  excluding `build/`, `.pytest_cache/`, `tests/fixtures/`, and `skills_bundle/**` generated
  stubs), `AGENTS.md`, `CLAUDE.md`.
- `PLACEHOLDER_TOKENS` — add — **closes the placeholder syntax**: exactly `<TAG>`,
  `<VERSION>`, `<PATH>`, `<HARNESS>`. Anything else in a pin position is a literal and is
  checked as one.
- `Finding` dataclass (`file`, `line`, `arm`, `message`) — add — the reported unit; mirrors
  `roadmap_lint`'s string-issue list but typed, since four arms need discriminating.
- `check_paths(text, path, repo) -> list[Finding]` — add — **arm 1**: every backtick-quoted
  token matching a repo-path shape (contains `/` or a known extension) resolves under `repo`.
  Skips fenced code blocks, URLs, and glob patterns containing `*`.
- `check_version_pins(text, path) -> list[Finding]` — add — **arm 2**: every
  `pip install X==V`, `@v<semver>`, or `<pkg>@<ref>` in a fenced block either matches a real
  git tag / the packaged version, or is one of `PLACEHOLDER_TOKENS`. Real-tag resolution is
  **offline** — reads `git tag --list` and `pyproject.toml` version, never the network.
- `check_inventories(text, path, repo) -> list[Finding]` — add — **arm 3**: a markdown table
  or list annotated with an inventory marker comment (see below) must have exactly one row
  per entry of its declared source directory. Unannotated tables are ignored — the check is
  opt-in per inventory, so it cannot become a nuisance gate on arbitrary tables.
- `check_command_contract(text, path) -> list[Finding]` — add — **arm 4, redefined**: for
  each command in a fenced block inside a section whose heading matches `quickstart|install`,
  the command must either (a) appear in `SELF_SUFFICIENT_COMMANDS`, or (b) have a
  prerequisite/effect note within the same block or the paragraph immediately following. It
  **executes nothing**. `SELF_SUFFICIENT_COMMANDS` is a small literal allowlist
  (`--help`, `--version`, `validate-roadmap`).
- `check_repo(repo) -> list[Finding]` — add — walks `ENTRY_DOC_GLOBS`, runs the four arms.
- `main(argv) -> int` — add — `0` clean, `1` findings (each printed `file:line [arm] message`
  to stderr), `2` usage/IO error. Mirrors `roadmap_lint.main`.

### `phase-loop-runtime/src/phase_loop_runtime/docs_surfaces.py` (modify)

- `DOC_SURFACE_GLOBS` — modify — add `"AGENTS.md"` and `"CLAUDE.md"`. They are agent-facing
  contract documents loaded by every session and are currently not doc surfaces at all
  (verified: zero occurrences). Mechanical prerequisite, not the deliverable.

### `phase-loop-runtime/tests/fixtures/entry_docs/` (create)

Static fixture docs, one per arm, so negatives never require mutating live documentation:

- `bad_path.md` — a backtick path that does not resolve.
- `bad_pin.md` — `pip install phase-loop-runtime==0.0.1` (a version that is not a real tag).
- `bad_inventory.md` — an annotated table with one row fewer than its source directory.
- `bad_command.md` — a quickstart command with neither allowlist membership nor a
  prerequisite note.
- `clean.md` — satisfies all four arms (the fixture-level positive control).

### `phase-loop-runtime/tests/test_entry_doc_check.py` (create)

- `test_current_repo_is_clean` — add — **the positive control**: `check_repo(<repo root>)`
  returns zero findings against the live entry docs. Without this, an always-failing check
  satisfies every negative arm.
- `test_<arm>_negative` ×4 — add — each fixture yields ≥1 finding, and the finding's `arm`
  field is the expected one (asserting the *arm*, not just non-emptiness, so a check that
  fails everything for the wrong reason does not pass).
- `test_placeholder_tokens_accepted` — add — `<TAG>`/`<VERSION>` in a pin position produce no
  finding, closing the syntax behaviourally rather than only in prose.
- `test_unannotated_table_ignored` — add — proves arm 3 is opt-in and cannot become a
  nuisance gate.
- `test_exit_codes` — add — `main()` returns 0 on the clean fixture, 1 on each bad fixture.

Fixture repos are built with `TemporaryDirectory()`, matching `test_docs_audit.py:84`.

### `.github/workflows/entry-doc-check.yml` (create)

Mirrors `docs-audit.yml` structurally, minus the diff machinery (this check needs no base
ref — that is the point).

- Trigger: `pull_request` and `push: branches [main]`. No tag trigger; this is not a
  release-surface gate.
- One job `entry-doc-check`, `runs-on: blacksmith-4vcpu-ubuntu-2404`, `timeout-minutes: 10`.
- Steps: `actions/checkout@v4` (default depth — **no `fetch-depth: 0`**, since no diff is
  computed, though arm 2 needs tags: use `fetch-tags: true`), setup-python 3.12,
  `pip install ./phase-loop-runtime`, then `python -m phase_loop_runtime.entry_doc_check --repo .`.

## Documentation impact

- `docs/agent-phase-convergence.md` — modify — its "Ban future-history pins — carefully"
  section tells readers a naive 40-hex scan produces false positives and needs an allowlist.
  Once this check exists, add one sentence naming it as the worked implementation.
- `CHANGELOG.md` — add — a new CI check is a public-surface change; the repo's docs-audit gate
  requires a CHANGELOG entry for public-surface changes, so omitting it fails that gate.
- `README.md`, `AGENTS.md`, `CLAUDE.md` — **no change**. The check verifies them; it does not
  document itself into them. (Adding an inventory marker comment to
  `phase-loop-skills/README.md`'s table is required for arm 3 to cover it — that is the one
  live-doc edit, and it is a comment, not prose.)

## Dependencies & order

1. `docs_surfaces.py` taxonomy addition first — independent, mechanical, and lets the
   change-coupled audit start observing `AGENTS.md`/`CLAUDE.md` immediately.
2. `entry_doc_check.py` with arms 1–2 (paths, pins) — the two arms that caught real defects
   and need no new markup.
3. Inventory marker comment in `phase-loop-skills/README.md`, then arm 3.
4. Arm 4 last — it is the weakest arm and the most likely to need scope negotiation.
5. Fixtures and tests alongside each arm, not batched at the end.
6. Workflow last, once `main()` exit codes are stable.

**Blocking external:** none. This touches no FABPUB surface (`cli.py`, broker, publish paths)
and no PROOFGATE surface. It can run concurrently with the in-flight phase.

## Verification

```sh
# From the repo root, with the runtime importable.
cd phase-loop-runtime

# Unit + integration for the new module (the positive control is in here).
PYTHONPATH=src:tests python3 -m pytest tests/test_entry_doc_check.py -q

# The positive control alone — must pass against the LIVE docs, or the check is
# unusable regardless of how well its negatives work.
PYTHONPATH=src python3 -m phase_loop_runtime.entry_doc_check --repo ..; echo "exit=$?"   # expect 0

# Each fixture negative, expecting exit 1 and the right arm named.
for f in bad_path bad_pin bad_inventory bad_command; do
  PYTHONPATH=src python3 -m phase_loop_runtime.entry_doc_check --file tests/fixtures/entry_docs/$f.md
  echo "$f exit=$?"   # expect 1
done

# Regression: the change-coupled audit still passes with the widened taxonomy.
PYTHONPATH=src:tests python3 -m pytest tests/test_docs_audit.py -q

# Mutation coupling: reintroduce the real historical defect and confirm it is caught.
git show 8f191d99:phase-loop-runtime/README.md > /tmp/old-runtime-readme.md   # contains @v0.1.5
PYTHONPATH=src python3 -m phase_loop_runtime.entry_doc_check --file /tmp/old-runtime-readme.md
echo "historical v0.1.5 pin exit=$?"   # expect 1 — the check must catch the defect that motivated it
```

Edge cases to exercise: a path inside a fenced code block (must not be checked as a live
path); a URL containing a slash (must not be treated as a repo path); a glob (`docs/**`);
an inventory whose source directory is empty; a quickstart block with no commands at all.

## Acceptance criteria

- [ ] `python -m phase_loop_runtime.entry_doc_check --repo .` exits **0** against the current
      clean entry docs, and this is asserted by `test_current_repo_is_clean` — an
      always-failing check cannot satisfy the negatives.
- [ ] Each of the four arms has a fixture negative that exits **1** and reports that arm by
      name, asserted per-arm rather than by non-empty output.
- [ ] The historical `@v0.1.5` pin from `phase-loop-runtime/README.md` at commit `8f191d99`
      is reported as a finding — the check catches the defect that motivated it.
- [ ] `<TAG>` and `<VERSION>` in a pin position produce no finding; any other unresolvable
      literal does.
- [ ] `AGENTS.md` and `CLAUDE.md` appear in `docs_surfaces.DOC_SURFACE_GLOBS`, and
      `tests/test_docs_audit.py` still passes unchanged.

## Execution Policy

- execute: effort=medium, reason=four independent parsing arms with false-positive risk;
  mechanical individually but the markdown-scanning edge cases (fenced blocks, URLs, globs)
  are where this will break.

## Scope honesty

Arm 4 as implemented checks a **documentation contract** (prerequisites are stated), not
executability. It therefore does not cover agent-harness#567 — the raw traceback from
`phase-loop run` in a fresh repo — which remains a separate runtime fix. Do not describe this
check as closing that defect, and do not attach a defect count to it: count the arms.
