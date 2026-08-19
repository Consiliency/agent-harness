# Detailed plan: make missing evidence fail loudly (agent-harness#607 + agent-harness#601)

## Task

Close one defect class with three observed instances: **the absence of evidence renders
identically to the presence of a positive result.** A check that never ran, a test that was
never collected, and a job that was skipped all read as "green" in every surface we consult.

Two issues, planned together because their fixes are the same primitive:

- **agent-harness#607** — a newly added workflow never runs against already-open PRs, so the
  first change to violate a brand-new gate can merge with the gate having never executed.
- **agent-harness#601** — tests that go inert in a CI lane are indistinguishable from tests
  that pass there.

## Research summary

**This repository has already solved this class once, correctly, for one workflow.** The
`suite gate` job in `.github/workflows/test.yml:126-152` exists precisely because a *skipped*
GitHub job satisfies a *required* status check. It is `if: always()`, `needs: [offload,
hosted]`, and asserts **exactly one** real verdict, failing with:

> "A skipped job satisfies a required status check, so this aggregate gate -- not
> offload/hosted individually -- is the required check. Both skipped means NO suite ran:
> that is a red, not a green."

That is this plan's thesis in the repo's own words, already shipped and load-bearing. The
work is to **generalise a proven pattern**, not to invent a mechanism.

Measured facts backing each half:

- **agent-harness#607** — `entry-doc-check.yml` landed on `main` at `b2659a7a` (2026-08-19
  00:00:06Z). agent-harness#545's last commit was 2026-08-16, three days earlier, so no
  `pull_request` event ever fired while the workflow existed and **GitHub created zero runs**
  for it. It merged 18:12:00Z and produced the workflow's first red on `main` six seconds
  later. Of 15 total runs, **0** were on its branch. A sweep found **13 of 17 open PRs have
  never run the check**; simulating each merge result gave **8 would-pass, 5 conflict,
  0 would-fail** — so the hole is currently *latent, not realised*, which sets the urgency
  but not the priority.
- **agent-harness#601** — comparing lanes in one offloaded run: Gate A skipped **138**, the
  canonical lanes **61**. Per-test junit diff: **78** skipped in Gate A but live in canonical
  (73 legitimately posture-dependent, 5 unclassified, **0 confirmed accidentally inert**),
  **41** present in the canonical collection and *absent from Gate A's* with **no reason
  string at all**, **88** that run only in Gate A, and **61** that skip in *both* lanes —
  of which **23** carry the bare reason `collection skipped`.

Gate A's tree is a sparse checkout staged by `phase-loop-runtime/scripts/gate_a_cleanroom.sh`,
which already emits junit via `GATE_A_JUNIT` (`:54-56`, `:189`). **The evidence needed for the
agent-harness#601 half already exists as an artifact**; nothing currently reads it.

## The class, stated once

Our tooling reports **what happened**. We read it as **what was verified**. Those diverge
exactly when *nothing happened*:

| instance | absent thing | renders as |
|---|---|---|
| branch protection | skipped job | required check satisfied |
| agent-harness#601 | uncollected / inert test | passing test |
| agent-harness#607 | non-existent workflow run | passing check |

The remedy in all three is the same: **assert the evidence exists, separately from asserting
it is positive.** `suite gate` does this for one workflow; this plan does it for workflow
*runs* and for test *collection*.

## Changes

### `.github/workflows/evidence-gate.yml` (create)

- `evidence-gate` job — add — **the agent-harness#607 half.** A required aggregate check,
  `if: always()`, that fails when a workflow this repo declares mandatory has **no run** for
  the PR head. Models `suite gate`'s shape: the *aggregate* is the required check, not the
  individual workflows, because an individual one cannot report its own non-existence.
- Resolve required workflows from a **checked-in list**, not from branch protection (the API
  needs admin scope and would make the gate's own correctness depend on a setting no reviewer
  sees in the diff).
- Failure message must name the remedy explicitly ("push an empty commit or re-run the
  workflow on this head"), matching `suite gate`'s precedent of explaining *why* a red is
  correct rather than only that it is red.

### `phase-loop-runtime/src/phase_loop_runtime/evidence_gate.py` (create)

- `required_runs_missing(...)` — add — pure function over `(declared_workflows,
  observed_runs)` returning the missing set. Pure so it is unit-testable without GitHub, the
  same design rule `native_agent_leg_request` follows.
- `inert_delta(canonical_junit, lane_junit)` — add — the **agent-harness#601 half**: returns
  three *separate* sets — `skipped_here_live_there`, `absent_from_collection`, and
  `skipped_in_both`. **Never a single total.** Summing them re-introduces exactly the
  conflation this plan exists to remove: a skip carries a reason and is auditable; an
  uncollected test carries nothing.
- `classify_inert(entry, allowlist)` — add — `legitimate` (matches a declared, reasoned
  allowlist entry), `unclassified`, or `accidental`.

### `.github/inert-tests-allowlist.json` (create)

- Declared inert set — add — one entry per legitimately posture-dependent test, each with a
  **reason string**. The measured baseline is 73 legitimate / 5 unclassified. Seed it with the
  73; the 5 unclassified are recorded as unclassified rather than silently admitted.
- Chosen over a bare skip *count* because 73 of 78 are stable, and a count says nothing about
  **which** test went inert — the count stays constant when one test goes inert and another
  becomes live.

### `phase-loop-runtime/scripts/gate_a_cleanroom.sh` (modify)

- Emit the **canonical-lane** junit path alongside the existing `GATE_A_JUNIT` so the two
  lanes can be diffed in CI — add — the artifact already exists per lane (`:54-56`, `:189`);
  only the pairing is missing.

### `.github/workflows/test.yml` (modify)

- Add an `inert-delta` step consuming both junit artifacts and failing on any
  `accidental` classification, or on growth in `absent_from_collection` — modify — placed
  with the existing gate rather than as a new required check, so the required-check set does
  not grow.

### `docs/` (modify)

- `docs/TEAM-ONBOARDING.md` — no change (installer-facing, not CI).
- **Documentation impact:** `CHANGELOG.md` — add — a new required check is a public surface;
  the docs-audit gate blocks a public-surface change without a committed CHANGELOG entry.

## Dependencies & order

1. `evidence_gate.py` pure functions **first** — everything else consumes them, and they are
   the only part testable without CI round-trips.
2. The allowlist must be seeded from a **fresh** measurement, not the numbers in this plan.
   Those were taken against `main` at `2344d030` and **expire on any merge** — that is
   agent-harness#607's own shelf-life property applying to this plan's inputs.
3. `evidence-gate.yml` lands **before** it is made a required check. A gate that is required
   before it is proven correct converts a false positive into a repo-wide outage.
4. **Blocking external dependency:** `ci/` and `.github/workflows/test.yml` are the
   offload/Dagger surface (agent-harness#534/#543 territory). This plan must be paneled and
   the design ratified before those files are edited.

## Verification

```sh
# Pure cores, no CI dependency
PYTHONPATH=src:tests python3 -m pytest tests/test_evidence_gate.py -q

# agent-harness#607 half, against the real hole: a branch whose last push predates a workflow
gh run list --workflow=<new-workflow>.yml --limit 100 --json headBranch --jq '.[].headBranch' | sort -u
# then set-difference against `gh pr list --json headRefName` -- the same method that
# measured 13 of 17, re-run to confirm the gate now reports them

# agent-harness#601 half, both directions
python3 -m phase_loop_runtime.evidence_gate --canonical junit-py310.xml --lane junit-gate-a.xml
# expect: three separate counts, never summed

# Falsifier -- REQUIRED, not optional
# 1. Mark a test skip-only-in-Gate-A that is NOT in the allowlist -> must classify `accidental`
# 2. Delete a workflow run's existence for a PR head -> evidence-gate must go red
```

## Acceptance criteria

- [ ] A PR whose head has **no run** for a declared-required workflow makes `evidence-gate`
      **red**, and the message names the remedy. Proven on a real branch, not a fixture.
- [ ] `inert_delta` reports `skipped_here_live_there`, `absent_from_collection`, and
      `skipped_in_both` as **three separate values**; no code path sums them.
- [ ] A test that goes inert in Gate A **and is not in the allowlist** fails the build;
      one that is in the allowlist, with a reason, does not.
- [ ] Each half is **mutation-verified against its own fixture**: neutering the missing-run
      detection fails only the agent-harness#607 test; neutering `classify_inert` fails only
      the agent-harness#601 test. A fix whose test passes with the fix removed is vacuous.
- [ ] The new check reaches the **entry point**: assert through the workflow/CLI verdict, not
      only the pure function. (Learned from agent-harness#604, where a builder was patched,
      the unit tests passed, and the board path was never reached.)
- [ ] `suite gate` behaviour is unchanged — this generalises the pattern, it does not
      replace the instance that already works.

## Execution Policy

- execute: effort=high, reason=CI gate correctness; a false positive here blocks every PR in
  the repo, and the failure mode being fixed is silent.

## Out of scope

- Branch-protection settings (`strict`, required contexts). Changing them is an operator
  action, not a code change, and this gate must prove itself before anything requires it.
- The 5 conflicted PRs from the agent-harness#607 sweep — unmergeable today, and their
  resolution produces a tree nobody has checked. That is the same latent shape, tracked
  separately rather than solved here.
- agent-harness#600 (entry-doc inventory scope) — unrelated surface.

## Manifest note

`plans/manifest.json` is **deliberately not appended** by this plan: agent-harness#606,
agent-harness#546, and agent-harness#383 all currently modify that file, and a fourth
concurrent edit would conflict three ways. Append the entry when those settle.
