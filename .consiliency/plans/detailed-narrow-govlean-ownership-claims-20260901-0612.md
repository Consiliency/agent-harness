# Detailed plan: narrow GOVLEAN's directory-wide ownership claims, measured not guessed

## Task

Consiliency/agent-harness#688. GOVLEAN's `Key files` carry four directory-wide claims
(`phase-loop-runtime/src/phase_loop_runtime/`, `phase-loop-runtime/tests/`, `skills-src/`,
`plans/`), so the roadmap-ownership check flags nearly every landed change and can never
graduate from advisory to blocking. Produce (a) a concrete narrowing proposal derived from
what GOVLEAN's commits actually touched, (b) the flag rate WITH that proposal applied,
computed by the real replay instrument rather than estimated, (c) the ah#683 selector fix if
still open, and (d) an analysis of the residual multi-phase overlap as input for a
cross-phase decision.

**Scope boundary, stated up front.** `specs/phase-plans-v10.md` is LEGIBLE-owned, and the
issue itself says this is a roadmap decision. This plan PRODUCES the measurement, the
candidate `Key files` text, and the tooling to score it. It does NOT edit the roadmap. The
edit is a separate, maintainer-authorized step, and the proposal is shaped so that step is a
paste rather than a judgment call. HARDEN is frozen at the codex agent's explicit request;
nothing HARDEN-claimed is touched, and see "Measured is not authorized" below for why that
matters to the proposal itself.

## Research summary

Targeted reads (the module is in-session; no Explore fan-out needed):

- **Baseline today, measured** (`--report 40 --base origin/main` at `ee3213ea`): **37/40
  flagged (92%)**; counterfactual with GOVLEAN claiming nothing: **13/40 (32%)**. Both worse
  than the issue's 82%/25% because more GOVLEAN-touching work has landed since, including
  ah#725. The number to beat is 32%, and it is a floor — narrowing GOVLEAN cannot go below it.
- **ah#683 is already fixed.** `_most_relievable_phase` (roadmap_ownership.py:836) ranks by
  `(-solely_claimed(a), -counts[a], a)`: most-*solely*-claimed first, frequency only as a
  tie-break. Pinned by `test_a_sole_cause_is_reported_as_a_sole_cause`. Deliverable (c) is a
  verification, not a change.
- **The injection point for a candidate roadmap** is `replay()` at roadmap_ownership.py:756;
  per-commit ownership is built at its line 41 (`mapping = ownership_map(blob.stdout)`, where
  `blob` is the roadmap AS IT EXISTED at that sha via `_roadmap_rel_at`). There is no
  override flag today. A candidate scores the same landed changes against ONE hypothetical
  text instead of the historical one at each commit.
- **GOVLEAN's claims are already qualified in prose** the matcher cannot read:
  `phase-loop-runtime/src/phase_loop_runtime/` "(new evidence, lint, and governance modules)",
  `phase-loop-runtime/tests/` "(new primitive tests; no frozen-surface edits)",
  `panel_invoker.py` "(EC-GOVLEAN-5 bounded edits)". The proposal makes the first two literal.
- **GOVLEAN's landed commits, measured** (ah#644 #672 #725 #670/#693 #711/#712 #714/#715
  #637), touched: `roadmap_ownership.py`, `closeout_classifier.py`, `agy_canary_evidence.py`,
  `profiles.py`, `prompts.py`; tests `test_roadmap_ownership.py`, `test_closeout_classifier.py`,
  `test_agy_canary_evidence.py`, `test_console_scripts_are_declared.py`,
  `test_phase_loop_execution_policy.py`, `test_model_class_policy.py`,
  `test_model_tier_taxonomy.py`, `test_phase_loop_launcher.py`; `skills-src/*/*-execute-phase/`
  and its regenerated outputs; `pyproject.toml`; `.phase-loop/CLAIMS.md`.
- **Measured is not authorized.** That same set includes `advisor_board/presets.py`,
  `advisor_board/CONTRACTS.md`, `capability_registry.py`, and `test_advisor_board_presets.py`
  from ah#715 — HARDEN files edited by mistake, which caused HARDEN's SL-0 restart. Deriving a
  claim from landed commits would launder that mistake into a standing claim. The proposal
  excludes them by name.
- **Residual 13 (GOVLEAN removed), by claimant set:** REVIEWTRUTH alone ×5; RELEASE alone ×2
  (`CHANGELOG.md`/`pyproject.toml`, the near-universal claims the audit renderer already
  demotes); HARDEN alone ×1; four multi-phase pile-ups, one with six claimants. Part 2 of the
  issue lives there and is cross-phase; this plan analyses it and stops.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/roadmap_ownership.py` (modify)
- `replay(repo, limit, roadmap_rel, rev, *, candidate_roadmap: str | None = None)` — modify —
  when `candidate_roadmap` is given, build `ownership_map(candidate_roadmap)` ONCE and use it
  for every replayed commit instead of the per-sha historical blob; still walk
  `_landed_commits` and `changed_paths` exactly as before so the sample is identical. Keep the
  per-sha path untouched when `None`. Reason: (b) requires scoring the SAME 40 changes against
  a hypothetical text.
- `ReplayRow` — modify — no shape change; but `render_report` must know the run was a
  candidate. Add a `candidate: bool = False` field with default so existing constructors and
  tests are unaffected.
- `render_report(rows)` — modify — when any row is a candidate run, the header reads
  `roadmap-ownership --report (CANDIDATE roadmap, not history)` and the "THIS is the
  graduation number" line is replaced by one saying it is a projection under a proposed
  roadmap. Reason: a hypothetical number that renders identically to a measurement is exactly
  the confusion this module exists to prevent.
- `main()` — modify — add `--candidate-roadmap PATH` (argparse); reject with exit 2 and a
  message if given without `--report`; read the file, fail closed (exit 2, CANNOT EVALUATE) if
  unreadable or if `ownership_map` rejects it (the canonical-lint gate and the intent/body
  counts from ah#725 apply to a candidate too — a malformed proposal must not score).

### `phase-loop-runtime/tests/test_roadmap_ownership.py` (modify)
- `TestCandidateRoadmap` — add — (1) a candidate text scores the same commit set as the
  historical run (assert identical `sha` sequence); (2) a candidate that drops a phase's
  claims lowers `notable` count for a commit touching that phase's file; (3) output header
  carries the CANDIDATE marker; (4) `--candidate-roadmap` without `--report` exits 2; (5) a
  malformed candidate exits 2 with CANNOT EVALUATE. Named mutations: (1) walk a different
  `rev`; (2) ignore `candidate_roadmap` and use the historical blob; (3) drop the header
  branch; (4) drop the argument check; (5) skip `ownership_map` validation on the candidate.
- No test in HARDEN's frozen 26 is touched (`test_roadmap_ownership.py` is GOVLEAN-only).

### `plans/govlean-key-files-proposal.md` (create)
- Proposal document, GOVLEAN-owned surface — add — carries: the measured file set with the
  PR that establishes each path; the exclusion list and why (HARDEN files from ah#715); the
  exact candidate `**Key files**` block ready to paste; the computed baseline and candidate
  numbers with the command that produced each; the residual-13 table for Part 2. Reason:
  the decision-maker should be able to act from one file, and every number in it must be one
  this plan actually computed.

### `specs/phase-plans-v10.md` (NOT modified)
- LEGIBLE-owned. The candidate text is delivered in the proposal document and posted to
  ah#688 for a maintainer/LEGIBLE decision. If that decision is "apply", the edit is a
  paste of the proposal's block plus a resealed `roadmap_sha256` in downstream plans — a
  separate authorized step, not part of this plan.

## Documentation impact
- `CHANGELOG.md` — modify — entry under `## [Unreleased]` for `--candidate-roadmap` and the
  CANDIDATE-marked report output (docs-audit gate requires it).
- `plans/govlean-key-files-proposal.md` — add — the proposal itself (above).
- Comment on Consiliency/agent-harness#688 — add — the candidate block, both numbers, and
  the residual table, with the reproduce command.
- No README/docs change: `--candidate-roadmap` is an instrument flag on an advisory tool, not
  a user-facing surface.

## Dependencies & order
1. `replay(candidate_roadmap=...)` + `ReplayRow.candidate` first — everything else consumes it.
2. `render_report` marker and `main()` flag, together (the flag is useless without the marker).
3. Tests + named mutations, run before any number is trusted.
4. **Only then** compute the candidate rate and write the proposal document; the document
   must quote output from step 3's instrument, not from a hand calculation.
5. CHANGELOG, commit, post to ah#688.
No external dependencies. HARDEN freeze is a constraint, not a dependency.

## Verification
```bash
W=/mnt/workspace/worktrees/ah-688-govlean; cd $W/phase-loop-runtime
PYTHONPATH=src:tests python3 -m pytest tests/test_roadmap_ownership.py -q            # all green
PYTHONPATH=src:tests python3 -m pytest tests/test_roadmap_ownership.py -q -k Candidate  # the 5 new tests
# named mutations (each must kill exactly its test): documented in the test docstrings
cd $W
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --report 40 --base origin/main                                            # baseline: 37/40, 13/40
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --report 40 --base origin/main --candidate-roadmap plans/govlean-candidate.md  # header says CANDIDATE
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.roadmap_ownership \
  --repo . --candidate-roadmap plans/govlean-candidate.md; echo "exit=$?"            # 2: needs --report
PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli docs-audit --repo .
```
Edge cases: candidate file missing → exit 2; candidate with a malformed phase heading → exit 2
via the ah#725 gates, NOT a silently smaller map; candidate identical to the live roadmap →
numbers identical to baseline (a sanity check that the candidate path changes nothing but the
text).

## Acceptance criteria
- [ ] `--report 40 --candidate-roadmap <file>` replays the identical sha sequence as
      `--report 40` and prints a header containing `CANDIDATE`; proven by
      `pytest -k Candidate` and the two report commands above diffing only in header + counts.
- [ ] The candidate rate in the proposal document equals the instrument's printed output for
      the committed candidate text, byte-for-byte on the `would have flagged (CANDIDATE
      PROJECTION):` line; proven by re-running the candidate command and `grep`-comparing.
      *Amended 2026-09-01 after the agent-harness#732 CR (codex, round 3): the line a consumer
      greps out must carry the projection label itself, so the label moved onto it.*
- [ ] `ah#683` verified fixed: `_most_relievable_phase` ranks solely-claimed first and
      `test_a_sole_cause_is_reported_as_a_sole_cause` kills the `if remaining:`→`if True:`
      mutation; proven by running that mutation.
- [ ] The proposal's exclusion list contains every HARDEN-claimed path that appears in
      GOVLEAN's measured set, each verified against the authority the proposal names for it:
      `roadmap-ownership --preflight <path>` reporting HARDEN for roadmap-claimed paths, and
      membership in `harden_tdd_guard.HARDEN_TEST_PATHS` for frozen-inventory paths (which
      `--preflight` cannot report — the frozen inventory is not roadmap ownership); paths on
      neither list are labelled "neither" explicitly. Proven by the verification table in the
      proposal, produced by the script quoted beside it.
      *Amended 2026-09-01 after the agent-harness#732 CR (codex, round 2): as first written
      the criterion could not pass for `test_advisor_board_presets.py` and
      `test_panel_invoker.py`, which are HARDEN-frozen but not HARDEN-roadmap-claimed. The
      amendment names the second authority instead of dropping the check.*
- [ ] `specs/phase-plans-v10.md` is unchanged on the branch (`git diff origin/main -- specs/`
      is empty).

## Execution Policy
- execute: effort=medium, reason=one bounded flag on an existing instrument; the discipline is
  in refusing to publish an uncomputed number, not in the code
