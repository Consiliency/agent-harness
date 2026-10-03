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

Amended after round 1 of the board review on agent-harness#1189. The original
whole-run snapshot credited writes by any command, and it accepted symlinks and
earlier phases' records. The design below replaces it with one rule: evidence is
what an observed invocation of the producer itself wrote, at the current commit.

### `phase-loop-runtime/src/phase_loop_runtime/generated_outputs.py` (create)
- `parse_declaration` / `load_declaration(repo)` — add — the closed v1 declaration,
  read from `HEAD` only. It rejects unknown keys, shell operators in `command`,
  unbounded globs, and reserved roots (case-insensitively).
- `ProducerRecorder` (`for_repo`, `before`, `after`, `run`, `write`) — add
  - Only an argv equal to a declared producer's is observed.
  - `before`/`after` snapshot that producer's own globs as `(digest, mtime_ns)`
    around one invocation. A file counts as "written" if it is new or its digest or
    mtime moved.
  - `write` binds the record to `HEAD` and the declaration's sha. It merges at the
    same HEAD and starts empty otherwise.
  - An unchanged entry carries forward only when its producer re-ran successfully.
  - On overlapping globs, the last writer wins.
  - A failed invocation withdraws that producer's entries.
- `file_identity` / `_regular_file_in_repo` — add — refuse symlinks and symlinked
  path components, both when recording and when accepting.
- `run_declared_producers(repo)` — add — implements `--record-outputs`. It is a no-op
  without a declaration.
- `verify_declared_output` — add. A file passes only if:
  - a declared glob covers it;
  - the record matches the declaration sha and HEAD;
  - the entry's producer covers it;
  - it is a regular file with an unchanged digest.
- `is_harness_handoff(repo, relpath)` — add. The file must carry the frontmatter
  contract with `from == dir` naming a shipped skill. Its `repo_root` must be this
  repo, its `commit` must exist here, and it must be a regular in-repo file.

**Round-2 amendment (board review at 68c5abf8):**
- **Written.** A file counts as written only if the invocation created it or changed
  its content, never on mtime alone.
- **Head per invocation.** Each invocation records its HEAD, before and after. `write`
  refuses to persist if HEAD moved.
- **Phase binding.** The record carries `phase`, resolved by
  `verification_evidence._phase_alias`, and both the merge and the audit require the
  same phase. The CLI gains `--phase`.
- **Clean rebuild.** `--record-outputs` first moves existing ignored, untracked
  declared outputs to `.phase-loop/generated-outputs/displaced/<stamp>/`. It never
  deletes them, and it runs each producer under `PHASE_LOOP_VERIFY_TIMEOUT_SECONDS`.
- **Shell syntax.** String commands are tokenised for shell syntax. In list commands,
  bare operator elements and a leading `NAME=` are rejected.
- **Handoff commit.** The handoff `commit` is read from the frontmatter only.
- **Malformed record entries** are dropped on load, so the file they name blocks.
- **AuditContext.** HEAD, phase, declaration and record are resolved once per audit.

**Round-3 amendment (board review at e797af15):**
- **Phase identity is supplied, never inferred.**
  - `launcher.launch` and `launch_with_spec` gain `phase_alias`, which stamps
    `PHASE_LOOP_PHASE_ALIAS` on the child.
  - Every runner and worker-pool launch site passes its live alias.
  - `generated_outputs.current_phase` is explicit, then that variable, then
    `PHASE_ALIAS`, then `None`, and it is never read from `state.json`. `None` means
    nothing is recorded or accepted.
  - A launch with no dispatched phase drops an inherited `PHASE_LOOP_PHASE_ALIAS`; the
    lease-supervisor re-entry keeps the outer stamp.
  - The execute prompt's audit command carries `--phase <alias>`, for the channel and
    agent-view routes, which bypass the launcher.
- **Producer timeouts** are validated: anything not finite and positive falls back to
  the default. Producers run in their own session, and the whole process group is
  killed on timeout.
- **`displaced/`** is pruned to the newest 5.

**Round-5 amendment (board review at b694dcb5; supersedes the round-3 phase-identity
bullets above):**
- **Phase identity is explicit only.** Every route the environment stamp missed
  (lane and repair prompts, channel and agent-view sessions) showed the stamp could not
  be made complete, so it is removed: `launch`/`launch_with_spec` take no
  `phase_alias`, and no launch site passes one. `current_phase` is the explicit alias
  or `None`.
- **`prompts.closeout_audit_instruction(phase)`** writes the audit command once, with
  `--phase <alias>`. The execute prompt inlines it; lane and repair prompts append it
  (`_with_closeout_audit`); delegated children are built through those branches.
- **`--record-outputs` without `--phase`** raises `PhaseIdentityError` before
  displacement (CLI exit 2).
- **Skills and the mismatch hint** show `--phase <ALIAS>`.
- `verification_evidence._phase_alias` is unchanged.

**Round-6 amendment (board review at 62e096ea):**
- `build_prompt` applies `_with_closeout_audit` at its single exit (no per-branch
  wraps): to every closing-out action (execute, repair, review), every harness lane,
  and every prompt whose skill pack holds an audit-prescribing skill
  (`AUDIT_PRESCRIBING_SKILLS`, pinned to a scan of the packaged skills).
- `current_phase` also refuses the bare placeholder words (`ALIAS`, `PHASE`, ...); the
  hint and docs print `<ALIAS>`; the skills print a shell-safe `--phase ALIAS`.

### `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` (modify)
- `observe_stages(observer)` / `_observed_stage` — add. A context-var seam brackets
  each command and suite stage of `run_verification`.
  - The public `run_verification` signature is unchanged, because LEGIBLE freezes it
    (`test_legible_evidence.py::test_public_compatibility_run_verification_load_validate_and_cli_signatures`).
  - The observer is evidence-only. Its exceptions are swallowed, and the artifact is
    unchanged.

### `phase-loop-runtime/src/phase_loop_runtime/closeout_classifier.py` (modify)
- `classify_ignored_output` — modify — drop the by-name handoff rule (agent-harness#1084).
- `audit_ignored_outputs` / `_grade_by_provenance` — modify
  - Expand collapsed ignored directories via `git ls-files -o -i`.
  - Grade each ignored file with the path rules, then the handoff contract, then the
    declared-output check.
  - Add the `declared_output` bucket and `unknown_reasons`.
- `main` — modify — add `--record-outputs`.

### `phase-loop-runtime/src/phase_loop_runtime/runner.py` (modify)
- `_run_execute_verification` — modify — run `run_verification` inside
  `observe_stages(ProducerRecorder)`, then write the record. A failure goes to stderr
  and to `generated_outputs_record_error`, and it never changes the outcome.

### Executor instructions (modify)
- `skills-src/{codex,gemini,claude}/*-execute-phase/SKILL.md` and `prompts.py` —
  modify — prescribe `phase-loop-closeout-audit --repo . --record-outputs` and update
  what exit 0 means. Regenerate the bundles and the launchspec golden. The
  `test_executor_exited_without_closeout_785.py` permitted-delta undo covers this
  prose.

### Tests
- `phase-loop-runtime/tests/test_closeout_generated_outputs.py` (create) — the
  Node/BAML regression through the real runner, plus every round-1 falsifier
  (codex F001–F003, Claude C1–C6, grok F1–F3).
- `phase-loop-runtime/tests/test_closeout_classifier.py` (modify, disclosed) — the
  handoff fixtures carry the full contract, and a path-only handoff is untrusted.

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
- `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_verification_evidence.py tests/test_hotfix_lane.py tests/test_launchspec_golden.py tests/test_skills_canon_parity.py tests/test_skills_bundle_drift.py tests/test_executor_exited_without_closeout_785.py tests/test_legible_evidence.py -q -p no:cacheprovider`
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
  - credit a failed producer;
  - round 6: review route unwrapped, the single-exit wrapper skipped, body not extended (codex delivery), placeholder words accepted;
  - round 5: read either environment key, a prompt route omits `--phase`, record without `--phase` after displacing, hint without `--phase`, prune keeps the oldest;
  - round 3: fall back to state.json, no launcher stamp, setdefault stamp, keep an inherited alias when none is dispatched, strip the stamp on lease re-entry, no `--phase` in the prompt, run_loop passes no alias, accept or record an unknown phase, unbounded timeout, kill the child only, no pruning;
  - round 2: mtime counts, no phase check, the epoch ignores phase, HEAD checked only at write, a straddle allowed, no displacement, displace tracked files, drop in-recording `mine`, allow string shell syntax, no default timeout, commit read from the whole file, corrupt entries kept, the CLI ignores `--phase`.

## Acceptance criteria
- [ ] A marker-valid handoff under a collapsed `/.dev-skills/` entry is `runner_owned`; an unmarked file there is `unknown_ignored`.
- [ ] After a real runner verification of declared producers, `.baml/ .cache/ baml_sdk/ dist/ generated/baml/` are `declared_output` and `main(["--repo", repo])` returns 0.
- [ ] An undeclared, hand-placed, pre-placed-then-chmod-ed, post-producer-edited, symlinked or undeclared-command-written ignored file makes `main` return 1, and so does a record taken at an earlier commit.
- [ ] In the next phase, `main(["--repo", repo, "--record-outputs"])` returns 0 after byte-identical regeneration.
- [ ] An unbounded (`**`) declaration is rejected, and an uncommitted declaration is not honoured.
