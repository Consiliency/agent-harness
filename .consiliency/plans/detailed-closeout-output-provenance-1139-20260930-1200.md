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
  runs the plan's `## Verification
- `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_closeout_generated_outputs.py tests/test_closeout_classifier.py -q -p no:cacheprovider`
- `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_verification_evidence.py tests/test_hotfix_lane.py tests/test_launchspec_golden.py tests/test_skills_canon_parity.py tests/test_skills_bundle_drift.py -q -p no:cacheprovider`
- `python -m pyflakes` on the changed modules.
- Named mutations, each of which must turn a test red:
  - accept a symlink leaf;
  - observe every command;
  - drop the HEAD binding;
  - always or never merge epochs;
  - drop carry-forward;
  - carry forward without a rerun;
  - credit a file by presence alone;
  - ignore mtime;
  - drop the digest check;
  - accept unknown keys;
  - accept shell syntax;
  - make the reserved-root check case-sensitive;
  - drop the handoff `repo_root` or `commit` check;
  - silence the runner error;
  - stop passing the observer;
  - make `--record-outputs` fail without a declaration;
  - credit a failed producer.

## Acceptance criteria
- [ ] A marker-valid handoff under a collapsed `/.dev-skills/` entry is `runner_owned`; an unmarked file there is `unknown_ignored`.
- [ ] After a real runner verification of declared producers, `.baml/ .cache/ baml_sdk/ dist/ generated/baml/` are `declared_output` and `main(["--repo", repo])` returns 0.
- [ ] An undeclared, hand-placed, pre-placed-then-chmod-ed, post-producer-edited, symlinked or undeclared-command-written ignored file makes `main` return 1, and so does a record taken at an earlier commit.
- [ ] In the next phase, `main(["--repo", repo, "--record-outputs"])` returns 0 after byte-identical regeneration.
- [ ] An unbounded (`**`) declaration is rejected, and an uncommitted declaration is not honoured.
