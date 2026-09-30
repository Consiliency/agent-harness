# Detailed plan: provenance-checked closeout audit for harness handoffs and declared build outputs (agent-harness#1139)

## Task
`phase-loop-closeout-audit --repo .` exits 1 (`unknown_ignored`) on outputs a normal
phase verification produces: the harness's own handoffs under `.dev-skills/handoffs/**`
and a Node/BAML project's declared build outputs (`.baml/`, `.cache/`, `baml_sdk/`,
`dist/`, `generated/baml/`). Accept them by provenance, not by name; everything else
stays fail-closed. Acceptance is the four items of agent-harness#1139, restated only as
testable checks below.

## Research summary
- `closeout_classifier.classify_ignored_output` is path-only. agent-harness#1084 added
  a by-name rule for `.dev-skills/handoffs/`, but `phase-loop init` (cli.py, `entry =
  "/.dev-skills/"`) writes `/.dev-skills/`, and `git status --ignored=matching` then
  reports the collapsed directory `!! .dev-skills/`, which the rule never matches.
  Reproduced on main: a repo with `/.dev-skills/`, `/dist/`, `.cache/` exits 1 with all
  three as unknown. Declared build outputs arrive collapsed in the same way.
- agent-harness#186 established that ignored-ness alone is never evidence. This change
  keeps that rule: ignored paths are accepted only by producer evidence.
- Handoff contract: every workflow skill writes
  `.dev-skills/handoffs/<harness>-<skill>/<run_id>.md|latest.md` with frontmatter that
  includes `from, timestamp, repo, repo_root, branch, branch_slug, commit, run_id,
  artifact`. `from` equals the skill directory, and the skill is one of the bundled
  `skills_bundle/` directories.
- The runner's verification (`runner._run_execute_verification` → `run_verification`)
  runs the plan's `## Verification` commands. `verification.json` is sealed and has a
  closed field inventory (`verification_evidence.py`), so evidence goes into a sibling
  record under `.phase-loop/` (already runner-owned), not into that artifact.
- Frozen corpora: none of the classifier or runner verification tests are in the
  EXECFIND, PANEL or PRESROUTE receipts, or in HARDEN `FROZEN_SL0_PATHS`.
  `runner.py` and `verification_evidence.py` are HARDEN production paths, not frozen
  test nodes. The agy qualification JSON pins `closeout_classifier.py`'s digest, which
  matters only at a release cut.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/generated_outputs.py` (create)
- `load_declaration(repo)` — add — reads `.phase-loop-generated-outputs.json` from
  `HEAD` only (`git show HEAD:`), so an uncommitted or ignored declaration never counts.
  Validates the schema, producer names, argv commands, and glob bounds: relative, no
  `..`, a literal first segment, and not `.git`, `.phase-loop`, `.codex` or `.dev-skills`.
  `**`/`*` roots are rejected.
- `snapshot_and_record(repo, declaration, ran_producers, source, run_id)` — add — at the
  END of a run, digests every file under each successful producer's globs and writes
  `.phase-loop/generated-outputs/record.json`, bound to the declaration's sha256.
- `record_verification_outputs(repo, result)` — add — the runner hook. A producer
  "ran" when its argv exactly equals a verification command or suite argv with exit 0.
- `run_declared_producers(repo)` — add — the CLI path for skill-driven phases. It runs
  every producer in declaration order, then records.
- `is_harness_handoff(repo, relpath)` — add — the marker check described in Research.
  The file must be a regular non-symlink `.md` at the exact depth.
- `verify_declared_output(repo, relpath, declaration, record)` — add — the file must be
  covered by a declared glob, the record must name it under a covering producer, and
  its current digest must equal the recorded one.

### `phase-loop-runtime/src/phase_loop_runtime/closeout_classifier.py` (modify)
- `classify_ignored_output` — modify — drop the by-name handoff rule (agent-harness#1084)
  so a handoff path needs the marker.
- `audit_ignored_outputs` — modify — expand an unresolved collapsed directory with
  `git ls-files -o -i --exclude-standard -z -- <dir>`, and grade each member: path
  rules, then the handoff marker (runner_owned), then declared output
  (new `declared_output` bucket). Any member that fails stays unknown and gets a
  per-path reason. A probe failure fails closed. An invalid declaration is a typed
  failure (exit 2).
- `main` — modify — add `--record-outputs`, then audit. Print per-path unknown reasons.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)
- `_run_execute_verification` — modify — call `record_verification_outputs` after
  `run_verification`, wrapped so it can never change the verification outcome or
  summary.

### `phase-loop-runtime/tests/test_closeout_generated_outputs.py` (create)
- A Node/BAML-shaped fixture with a real producer run through
  `_run_execute_verification`. Two producers cross-write `.cache/`, and the fixture
  adds a marker-valid handoff. The audit must exit 0. Negatives cover a hand-placed
  file in `dist/`, an edited generated file, a failed producer, an unmarked handoff,
  a `**` declaration, an uncommitted declaration, and no record.

### `phase-loop-runtime/tests/test_closeout_classifier.py` (modify, disclosed)
- `test_the_required_skill_handoff_root_does_not_block` — modify fixture — write a
  marker-valid handoff, because a bare `from:` line is no longer enough.
- `test_only_the_exact_handoff_root_is_recognised` — modify — a path-only verdict for
  handoff strings is now `unknown_ignored` by design, and the marker is graded in the
  audit.

## Documentation impact
- `docs/phase-loop/closeout-generated-outputs.md` — add — the consumer declaration
  format, where the evidence comes from, the threat model, and the CLI.
- `CHANGELOG.md` — add — an Unreleased entry for agent-harness#1139.
- `phase-loop-runtime/README.md` — modify — one line pointing at the doc, near the
  closeout-audit mention.

## Dependencies & order
The `generated_outputs` module comes first, then the classifier, the runner hook, the
tests, and the docs.

## Verification
- `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_closeout_generated_outputs.py tests/test_closeout_classifier.py -q -p no:cacheprovider`
- `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_verification_interpreter_guard_221.py tests/test_agy_canary_evidence.py -q -p no:cacheprovider -k "closeout or console"`
- `python -m pyflakes phase-loop-runtime/src/phase_loop_runtime/generated_outputs.py phase-loop-runtime/src/phase_loop_runtime/closeout_classifier.py`
- Mutation checks. Each of these must turn a test red:
  - drop the digest comparison;
  - drop `from == dir`;
  - skip the expansion of collapsed directories;
  - accept a `**` glob;
  - count a producer with a non-zero exit.

## Acceptance criteria
- [ ] A marker-valid handoff under a collapsed `/.dev-skills/` entry is `runner_owned`; an unmarked file there is `unknown_ignored`.
- [ ] After a real runner verification of declared producers, `.baml/ .cache/ baml_sdk/ dist/ generated/baml/` are `declared_output` and `main(["--repo", repo])` returns 0.
- [ ] An undeclared, hand-placed or post-producer-edited ignored file makes `main` return 1.
- [ ] An unbounded (`**`) declaration is rejected, and an uncommitted declaration is not honoured.
