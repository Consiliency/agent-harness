# Detailed plan: close the six carried board items on the review-seat sandbox proposal

## Task

Apply the six non-blocking items carried out of the Consiliency/agent-harness#849 round-2 board
record ([comment 5676858188](https://github.com/Consiliency/agent-harness/pull/849#issuecomment-5676858188))
to the two merged proposal documents, then re-panel the revision with the same four seats.

The items were raised by the fable seat against `eed27d6d` and deliberately not applied, because
applying them would have changed the reviewed head after a 4/4 AGREE. They are now the first
post-merge revision of the proposal, which is re-panel 1 of the 2 the stopping rule allows.

## Research summary

No reconnaissance was run. Both files were authored and reviewed in this session, the board reports
are on disk under `/mnt/workspace/board-tools/sandbox-roadmap-pr849-r{1,2}/`, and the exact lines to
change are quoted below from the merged files at `origin/main` (`83f41b9a`). The proposal landed as
`1596b236` (agent-harness#849) and no commit has touched `docs/proposals/` since.

Two constraints carry over and are unchanged by this plan:
- the proposal must stay non-executable — no `specs/`, `plans/manifest.json`, or registry change, and
  nothing may read `docs/proposals/`;
- exit criteria cite agent-harness#848 Phase-0 gates by number and EC IDs by ID; they never restate them.

## Changes

### `docs/proposals/review-seat-sandbox.phases.md` (modify)

- `EC-SBXEXEC-7` (line 25) — modify — its falsifier names only one of EC-HARDEN-5's three falsifier
  clauses, so it drifts from the criterion it cites. Replace the falsifier with "any EC-HARDEN-5
  falsifier firing on such a path".
- `EC-SBXFETCH-6` (lines 74–77) — modify — two claim clauses have no falsifier. Add one for the
  snapshot being unreadable from the shared-layer build, and one for a build backend outside the
  pin's admitted set.
- `EC-SBXSEAT-3` (line 116) — modify — "a recorded pass" is not bound to the built code, while the
  proposal promises evidence against the built code. Require the record to be content-bound in the
  EC-GOVLEAN-2 form, citing that ID.
- `EC-SBXSEAT-5` (lines 120–122) — modify — same defect on "calibration record". Require the same
  content-bound form.
- `EC-SBXSEAT-6` (line 123) — modify — the claim says "while EC-HARDEN-5 is UNMET", but the falsifier
  fires only on a *recorded* UNMET, so an absent record passes. Falsify on any state other than MET,
  absent included.

### `docs/proposals/review-seat-sandbox.md` (modify)

- `## Pinned inputs`, gate-evidence row (line 29) — modify — "pinned when it passes, before
  activation" has no home once this file stops being authoritative at promotion. Point post-promotion
  gate evidence at the phases' own closeout evidence.
- `## Promotion rule`, trigger 2 (line 102) — modify — the parenthetical names one of gate 9's four
  checks. Say every check of gate 9, since "the real test subset passes" is the design-invalidating
  host fact.
- `## Promotion rule`, promotion-PR obligations (lines 88–93) — modify — add carrying the gate 9 and
  11 evidence digests into v10, so the pins survive the move out of `docs/proposals/`.
- `## Promotion rule`, Mechanics (lines 97–98) — modify — "every committed or executing plan" is dead
  text, because the Fallback forbids amending at all when an executing plan exists. Drop "or
  executing" and say the executing check is evaluated at the promotion PR's merge, not only when it
  opens.
- `## Promotion rule`, Stopping rule (lines 113–115) — modify — say whether a revision that only pins
  evidence digests counts as a re-panel. It does not: it changes no obligation.
- `## Promotion rule`, new sentence under the obligations — add — record that the SBXEXEC detailed
  plan must name the test subset and fixture layer satisfying gate 9's positive control, which has to
  pass at SBXEXEC closeout, before the fetch pipeline that EC-SBXFETCH-4 later requires exists.

## Documentation impact

The two changed files are themselves documentation, and they are enumerated above. No other
cross-cutting document is affected: this PR adds no public surface, no entry-point doc reference, and
no CHANGELOG-visible behaviour, exactly as agent-harness#849 did not.

## Dependencies & order

No ordering constraints between the edits; they touch disjoint lines in two files.

External deconfliction, checked at planning time: codex is executing agent-harness#825 in
`/mnt/workspace/worktrees/agent-harness-json-depth-825-20260916`, touching
`phase-loop-runtime/scripts/verify_harden_evidence.py`, a new test, and `plans/manifest.json`. This
plan touches none of those. `verify_harden_evidence.py` appears in this proposal only as a Key-files
path string in a phase that depends on HARDEN, so codex's edit and this one cannot collide.

**Deliberate deviation from the skill's closeout:** no `plans/manifest.json` entry is appended for
this plan. Codex has an uncommitted manifest append in flight for agent-harness#825 right now, and a
second append from a parallel branch would conflict textually in the same JSON array. The plan file
is committed without a manifest row; the row can be added later if the convention requires it.

## Verification

Run from the worktree root:

```bash
# 1. the proposal's own recipe, verbatim, extracted from the file under review
sed -n '/^```bash/,/^```$/p' docs/proposals/review-seat-sandbox.md | sed '1d;$d' > /tmp/recipe.sh
bash /tmp/recipe.sh     # expect: digest OK; lint OK 17 phases; coherence OK; ownership 28/30

# 2. the v10 bytes are untouched by this PR
git diff --stat origin/main..HEAD -- specs/ plans/manifest.json specs/roadmap-status.json   # expect: empty

# 3. no restatement crept back in: every gate-carrying falsifier imports the whole gate
grep -c 'any check of agent-harness#848 Phase-0 gate' docs/proposals/review-seat-sandbox.phases.md  # expect: 9

# 4. the docs gates that ran green on agent-harness#849
PYTHONPATH=$PWD/phase-loop-runtime/src python3 -m phase_loop_runtime.cli docs-audit --repo . --json
PYTHONPATH=$PWD/phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_entry_doc_check.py
```

CI is the authority for the merge gate; the suite runs offloaded and must be green before merge.

## Acceptance criteria

- [ ] Every one of the six carried items is closed in the diff, each traceable to the line named in `## Changes`.
- [ ] `bash /tmp/recipe.sh` exits 0 with digest OK, composed lint OK at 17 phases, coherence OK, and an unchanged 28/30 ownership flag rate.
- [ ] `git diff origin/main..HEAD` touches only `docs/proposals/*.md` and this plan file: no `specs/`, no `plans/manifest.json`, no registry, no runtime code.
- [ ] A four-seat board round on the revision returns 4/4 AGREE with no BLOCKING item, and the record is posted on the PR before merge.

## Execution Policy

- execute: effort=low, reason=docs-only wording change with no runtime surface
